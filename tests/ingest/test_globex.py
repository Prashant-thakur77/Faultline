"""globex generator (no FalkorDB): deterministic, acme-shaped, the planned sizes, and ids that never
collide across labels or with acme (the isolation tests look for acme ids)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from faultline.graph.schema_model import NODE_LABELS, REL_TYPES
from faultline.ingest import baselines, cross_domain, docs, history, lineage_to_graph, org_gen, otel_topology
from faultline.ingest import globex
from faultline.ingest.clock import HISTORY_END_MS, HISTORY_START_MS, ROTA_END_MS, ROTA_START_MS
from faultline.ingest.globex import embeddings as gx_embeddings
from faultline.ingest.globex import org as gx_org
from faultline.ingest.globex import topology as gx_topology

ROOT = Path(__file__).resolve().parents[2]
B = globex.build()
NODES = {lbl: {r["id"]: r for r in rows} for lbl, rows in B.nodes.items()}
SPEC = globex.load_spec()


def _canon(b) -> str:
    return json.dumps({"n": {k: v for k, v in sorted(b.nodes.items())},
                       "e": {"|".join(k): v for k, v in sorted(b.edges.items())}}, sort_keys=True, default=str)


def _rows(rel, src=None, dst=None):
    return [r for (t, s, d), rows in B.edges.items() if t == rel and src in (None, s) and dst in (None, d) for r in rows]


def test_deterministic_in_process():
    assert _canon(globex.build()) == _canon(globex.build(42)) == _canon(B)
    assert _canon(globex.build(7)) != _canon(B)


def test_deterministic_across_processes_and_hash_seeds():
    code = ("import hashlib,json;from faultline.ingest import globex as g;b=g.build();"
            "print(hashlib.sha256(json.dumps({'n':{k:v for k,v in sorted(b.nodes.items())},"
            "'e':{'|'.join(k):v for k,v in sorted(b.edges.items())}},sort_keys=True,default=str).encode()).hexdigest())")
    out = set()
    for hs in ("0", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hs, "PYTHONPATH": str(ROOT / "backend")}
        out.add(subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True, text=True).stdout.strip())
    assert len(out) == 1


def test_sizes_match_the_plan():
    assert len(NODES["Service"]) == 200
    assert len(NODES["Team"]) == 12
    assert len({s["domain"] for s in NODES["Service"].values()}) == 12
    assert len(NODES["Datastore"]) == 6
    assert len(NODES["Person"]) == 180
    assert len(NODES["Incident"]) == len(NODES["Postmortem"]) == 150
    assert 15 <= sum(1 for p in NODES["Person"].values() if not p["active"]) <= 20  # ~10% inactive
    assert sum(1 for s in NODES["Service"].values() if s["entry"]) == 1


def test_whitelisted_and_tenant_scoped():
    assert set(B.nodes) <= NODE_LABELS
    for rel, src, dst in B.edges:
        assert rel in REL_TYPES and src in NODE_LABELS and dst in NODE_LABELS
    for rows in B.nodes.values():
        for r in rows:
            assert r["tenant"] == "globex" and isinstance(r["id"], str) and r["id"]


def test_ids_unique_across_labels():
    ids = Counter(r["id"] for rows in B.nodes.values() for r in rows)
    dupes = sorted(i for i, c in ids.items() if c > 1)
    assert not dupes, dupes[:20]


def test_no_acme_id_appears_in_globex():
    acme = set()
    for m in (lineage_to_graph, otel_topology, cross_domain, baselines, org_gen, history, docs):
        for rows in m.build().nodes.values():
            acme |= {r["id"] for r in rows}
    globex_ids = {r["id"] for rows in B.nodes.values() for r in rows}
    assert not acme & globex_ids, sorted(acme & globex_ids)[:20]
    for probe in ("payment", "checkout", "inc-h005", "ADR-012", "p-001", "team-payments"):
        assert probe in acme and probe not in globex_ids


def test_every_edge_endpoint_exists():
    known = {(lbl, i) for lbl, rows in NODES.items() for i in rows}
    for (rel, sl, dl), rows in B.edges.items():
        for r in rows:
            assert (sl, r["src"]) in known, (rel, sl, r["src"])
            assert (dl, r["dst"]) in known, (rel, dl, r["dst"])


def test_failure_flow_mirrors_calls_with_criticality_caps():
    t = gx_topology.generate()
    calls = {(c.client, c.server): c for c in t.calls}
    prop = {(r["src"], r["dst"]): r["props"] for r in _rows("PROPAGATES_TO")}
    dep = {(r["dst"], r["src"]) for r in _rows("DEPENDS_ON")}
    assert set(prop) == dep
    assert set(prop) == {(c.server, c.client) for c in t.calls if c.cap > 0}
    for c in t.calls:
        assert c.cap in (0.0, 0.02, 1.0), c
        assert c.cap == 1.0 or c.why, f"best-effort/async cap needs a reason: {c}"
        assert c.rps >= 1
    for (u, v), p in prop.items():
        assert p["cap"] == calls[(v, u)].cap and p["w"] == 1 and p["domain"] == "service" and p["cut_cost"] >= 0


def test_call_graph_is_a_dag_with_preferential_hubs():
    t = gx_topology.generate()
    out = defaultdict(list)
    for c in t.calls:
        out[c.client].append(c.server)
    state: dict[str, int] = {}

    def visit(n: str) -> None:  # iterative-enough for 200 nodes
        state[n] = 1
        for m in out[n]:
            assert state.get(m) != 1, f"cycle through {n}->{m}"
            if m not in state:
                visit(m)
        state[n] = 2

    for n in t.label:
        if n not in state:
            visit(n)
    indeg = Counter(c.server for c in t.calls)
    top = [n for n, _ in indeg.most_common(5)]
    assert indeg[top[0]] >= 30  # preferential attachment → hubs
    batch = {s["id"] for s in t.services if s["batch"]}
    for s in t.services:
        if s["id"] != t.entry and s["id"] not in batch:
            assert indeg[s["id"]] >= 1, f"{s['id']} has no caller"


def test_flag_levers_cut_real_flow_edges():
    prop = {(r["src"], r["dst"]) for r in _rows("PROPAGATES_TO")}
    levers = [f for f in NODES["FeatureFlag"].values() if f["cuts_src"]]
    assert len(levers) >= 4
    for f in levers:
        assert (f["cuts_src"], f["cuts_dst"]) in prop


def test_org_shape_and_rota():
    org = gx_org.generate()
    people = {p.id: p for p in org.people}
    assert sum(1 for p in org.people if p.role == "vp") == 1
    for p in org.people:
        if p.role != "vp":
            assert p.manager in people
    for t, _ in org.teams:
        weeks = sorted((r for r in org.rota if r.team == t), key=lambda r: r.from_ms)
        assert weeks[0].from_ms == ROTA_START_MS and weeks[-1].to_ms == ROTA_END_MS
        for a, b in zip(weeks, weeks[1:]):
            assert a.to_ms == b.from_ms
        for r in weeks:
            assert people[r.person].valid_to is None or people[r.person].valid_to >= r.to_ms
        assert sum(1 for m in org.members[t] if people[m].active) >= 3
    collab = {(r["src"], r["dst"]): r["props"]["w"] for r in _rows("COLLABORATES")}
    assert all(collab[(b, a)] == w for (a, b), w in collab.items())


def test_ownership_one_current_owner_except_orphans():
    owns = Counter(r["dst"] for r in _rows("OWNS"))
    orphans = {o["component"] for o in SPEC["orphans"]}
    comps = set(NODES["Service"]) | set(NODES["Datastore"])
    for c in comps:
        assert owns[c] == (0 if c in orphans else 1), c
    gap_ready = [c for c in orphans if NODES["Service"][c]["revenue_path"]]
    assert gap_ready, "an orphaned revenue-path service makes Q-GAP-1 report a no_owner row"


def test_history_window_and_incident_shape():
    for d in NODES["Deploy"].values():
        assert HISTORY_START_MS <= d["at"] <= HISTORY_END_MS
    for c in NODES["Commit"].values():
        assert c["at"] >= HISTORY_START_MS
    has_sym = Counter(r["src"] for r in _rows("HAS_SYMPTOM"))
    caused = Counter(r["dst"] for r in _rows("CAUSED"))
    resolved = Counter(r["dst"] for r in _rows("RESOLVED"))
    pm = Counter(r["dst"] for r in _rows("DOCUMENTS"))
    roles = defaultdict(set)
    for r in _rows("AFFECTED"):
        roles[r["src"]].add(r["props"]["role"])
    for iid in NODES["Incident"]:
        assert has_sym[iid] == caused[iid] == resolved[iid] == pm[iid] == 1, iid
        assert {"cause", "symptom"} <= roles[iid]
    verdicts = Counter(a["verdict"] for a in NODES["Action"].values())
    assert verdicts["APPLIED"] == 150 and verdicts["NOT_APPLIED"] >= 1
    for s in NODES["Symptom"]:
        assert s.startswith("sym-")


def test_eight_families_by_cause_and_symptom():
    cause_of = {r["src"]: r["dst"] for r in _rows("AFFECTED") if r["props"]["role"] == "cause"}
    sym_of = {r["src"]: r["dst"] for r in _rows("HAS_SYMPTOM")}
    fams = Counter((cause_of[i], sym_of[i]) for i in NODES["Incident"])
    assert len(fams) == len(SPEC["archetypes"]) == 8
    assert sorted(fams.values()) == sorted(a["count"] for a in SPEC["archetypes"])


def test_bus_factor_cases_exist():
    commits = defaultdict(Counter)
    for r in _rows("COMMITTED"):
        commits[r["dst"]][r["src"]] = r["props"]["n"]
    expert = SPEC["org"]["departed_expert"]["component"]
    top, n = commits[expert].most_common(1)[0]
    assert not NODES["Person"][top]["active"] and n / sum(commits[expert].values()) > 0.5
    for comp in SPEC["org"]["dominant_active"]:
        top, n = commits[comp].most_common(1)[0]
        assert NODES["Person"][top]["active"] and n / sum(commits[comp].values()) > 0.5


def test_decisions_supersession_chain_and_runbooks():
    sup = {r["src"]: r["dst"] for r in _rows("SUPERSEDES")}
    assert sup == {"ADR-007": "ADR-002", "ADR-031": "ADR-007"}
    assert NODES["Decision"]["ADR-031"]["status"] == "active"
    for d in NODES["Decision"].values():
        assert d["rule_key"] and d["rule_op"] and d["url"].startswith("data/gen/docs/globex/")
        assert (ROOT / d["url"]).exists()
    rb_sym = {r["dst"] for r in _rows("RUNBOOK_FOR", "Runbook", "Symptom")}
    assert rb_sym <= set(NODES["Symptom"])


def test_embeddings_cover_memory_nodes_with_the_shared_model():
    from faultline.memory.embed import DIM, MODEL

    eb = gx_embeddings.build()
    for label in ("Incident", "Postmortem", "Runbook"):
        rows = eb.nodes[label]
        assert {r["id"] for r in rows} == set(NODES[label]), label
        assert all(len(r["embedding"]) == DIM and r["embedding_model"] == MODEL for r in rows)


@pytest.mark.parametrize("label", ["incident", "postmortem", "runbook"])
def test_embedding_files_match_current_texts(label):
    """The committed vectors were computed from today's generator output (regenerate if this fails)."""
    sys.path.insert(0, str(ROOT / "data" / "gen"))
    import embed_globex

    texts = dict(embed_globex.texts()[label.capitalize()])
    doc = json.loads((globex.EMBED_DIR / f"globex_{label}.json").read_text())
    assert {it["id"]: it["text"] for it in doc["items"]} == texts

