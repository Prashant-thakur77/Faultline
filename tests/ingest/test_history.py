"""history: deterministic 120-day change + incident history (no FalkorDB)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from faultline.graph.schema_model import NODE_LABELS, REL_TYPES
from faultline.ingest import history, org_gen
from faultline.ingest.clock import DAY_MS, HISTORY_END_MS, HISTORY_START_MS

ROOT = Path(__file__).resolve().parents[2]


def _canon(b) -> str:
    return json.dumps({"n": {k: v for k, v in sorted(b.nodes.items())},
                       "e": {"|".join(k): v for k, v in sorted(b.edges.items())}}, sort_keys=True)


def _rows(b, rel, src=None, dst=None):
    return [r for (t, s, d), rows in b.edges.items()
            if t == rel and src in (None, s) and dst in (None, d) for r in rows]


B = history.build()
ORG_B = org_gen.build()
ORG = org_gen.generate()
NODES = {lbl: {r["id"]: r for r in rows} for lbl, rows in B.nodes.items()}
INCIDENTS = NODES["Incident"]


def _cause(iid):
    return next(r["dst"] for r in _rows(B, "AFFECTED") if r["src"] == iid and r["props"]["role"] == "cause")


def _symptom(iid):
    return next(r["dst"] for r in _rows(B, "HAS_SYMPTOM") if r["src"] == iid)


def test_deterministic_in_process():
    assert _canon(history.build()) == _canon(history.build(42)) == _canon(B)
    assert _canon(history.build(7)) != _canon(B)


def test_deterministic_across_processes_and_hash_seeds():
    code = ("import hashlib,json;from faultline.ingest import history as h, org_gen as o;"
            "c=lambda b: json.dumps({'n':{k:v for k,v in sorted(b.nodes.items())},"
            "'e':{'|'.join(k):v for k,v in sorted(b.edges.items())}},sort_keys=True);"
            "print(hashlib.sha256((c(h.build())+c(o.build())).encode()).hexdigest())")
    out = set()
    for hs in ("0", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hs, "PYTHONPATH": str(ROOT / "backend")}
        out.add(subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True,
                               text=True).stdout.strip())
    assert len(out) == 1


def test_whitelisted_and_tenant_scoped():
    assert set(B.nodes) <= NODE_LABELS
    for rel, src, dst in B.edges:
        assert rel in REL_TYPES and src in NODE_LABELS and dst in NODE_LABELS
    for rows in B.nodes.values():
        for r in rows:
            assert r["tenant"] == "acme" and isinstance(r["id"], str)
        assert len({r["id"] for r in rows}) == len(rows)


def test_every_edge_endpoint_exists():
    topo = yaml.safe_load(org_gen.TOPOLOGY_PATH.read_text())
    known = {(lbl, r["id"]) for b in (B, ORG_B) for lbl, rows in b.nodes.items() for r in rows}
    known |= {("Service", s["id"]) for s in topo["services"]}
    known |= {("Datastore", d["id"]) for d in topo["datastores"]}
    transforms, kpis = org_gen.data_components()
    known |= {("Transform", t) for t in transforms} | {("KPI", k) for k in kpis}
    for (rel, src, dst), rows in B.edges.items():
        for r in rows:
            assert (src, r["src"]) in known, (rel, src, r["src"])
            assert (dst, r["dst"]) in known, (rel, dst, r["dst"])


def test_no_scenario_ids_leak():
    blob = _canon(B) + _canon(ORG_B)
    for lit in ("D-pay-417", "D-email-88", "D-rec-12", "D-cutover-1"):
        assert lit not in blob
    assert not re.search(r"\bD-[a-z]+-\d+", blob)


def test_ids_are_readable_and_stable_shapes():
    assert all(re.fullmatch(r"c-[0-9a-f]{8}", i) for i in NODES["Commit"])
    assert all(re.fullmatch(r"pr-\d+", i) for i in NODES["PR"])
    assert all(re.fullmatch(r"dep-\d+", i) for i in NODES["Deploy"])
    assert sorted(INCIDENTS) == [f"inc-h{i:03d}" for i in range(1, 41)]
    assert sorted(NODES["Postmortem"]) == [f"pm-h{i:03d}" for i in range(1, 41)]
    assert sorted(NODES["Repo"]) == sorted(f"repo-{t}" for t, _ in org_gen.TEAMS)


def test_everything_inside_the_history_window():
    times = [c["at"] for c in NODES["Commit"].values()] + [d["at"] for d in NODES["Deploy"].values()]
    times += [p["merged_at"] for p in NODES["PR"].values()]
    for i in INCIDENTS.values():
        times += [i["onset_at"], i["opened_at"], i["resolved_at"], i["last_used"]]
        assert i["onset_at"] <= i["opened_at"] < i["resolved_at"] == i["last_used"]
    assert HISTORY_START_MS <= min(times) and max(times) <= HISTORY_END_MS


def test_deploy_volume_and_kinds():
    deploys = NODES["Deploy"].values()
    per_day = len(deploys) / 119
    assert 2.0 <= per_day <= 4.0
    assert {d["kind"] for d in deploys} == {"deploy", "config", "flag", "data_cutover"}
    changed = {r["src"]: r["dst"] for r in _rows(B, "CHANGED")}
    assert all(changed[d["id"]] == d["target_id"] for d in deploys)
    # every commit ships in exactly one deploy and exactly one PR
    assert Counter(r["dst"] for r in _rows(B, "CONTAINS", "Deploy", "Commit")) == Counter(list(NODES["Commit"]))
    assert Counter(r["dst"] for r in _rows(B, "CONTAINS", "PR", "Commit")) == Counter(list(NODES["Commit"]))


def test_committed_aggregates_match_commits():
    per = Counter((c["author_id"], c["component_id"]) for c in NODES["Commit"].values())
    agg = {(r["src"], r["dst"]): r["props"]["n"] for r in _rows(B, "COMMITTED")}
    assert agg == dict(per)


def _bus(component):
    rows = sorted(((r["props"]["n"], r["src"]) for r in _rows(B, "COMMITTED") if r["dst"] == component),
                  reverse=True)
    total = sum(n for n, _ in rows)
    return rows[0][1], rows[0][0] / total


def test_bus_factor_one_components():
    top, share = _bus("quote")
    assert share > 0.5 and ORG.person(top).active
    top, share = _bus("currency")
    assert share > 0.5 and not ORG.person(top).active
    comps = {r["dst"] for r in _rows(B, "COMMITTED")}
    assert sum(1 for c in comps if _bus(c)[1] > 0.5) >= 2


def test_forty_incidents_fully_formed():
    assert len(INCIDENTS) == 40
    for iid, i in INCIDENTS.items():
        assert i["salience"] == i["salience_base"] == 1.0 and i["confident"] is True and i["title"]
        assert sum(r["src"] == iid for r in _rows(B, "HAS_SYMPTOM")) == 1
        assert sum(r["dst"] == iid for r in _rows(B, "CAUSED")) == 1
        assert sum(r["dst"] == iid for r in _rows(B, "RESOLVED")) == 1
        assert sum(r["dst"] == iid for r in _rows(B, "DOCUMENTS")) == 1
        roles = Counter(r["props"]["role"] for r in _rows(B, "AFFECTED") if r["src"] == iid)
        assert roles["cause"] == 1 and roles["symptom"] == 1
        acts = [NODES["Action"][r["dst"]] for r in _rows(B, "RESOLVED_BY") if r["src"] == iid]
        assert any(a["verdict"] == "APPLIED" for a in acts)
    # the causing deploy changed the cause component, before onset
    for r in _rows(B, "CAUSED"):
        dep, inc = NODES["Deploy"][r["src"]], INCIDENTS[r["dst"]]
        assert dep["target_id"] == _cause(r["dst"]) and dep["at"] < inc["onset_at"]
    # AFFECTED keys are distinct per (incident, component) pair, so MERGE keeps every role
    pairs = Counter((r["src"], r["dst"], r["props"]["key"]) for r in _rows(B, "AFFECTED"))
    assert max(pairs.values()) == 1


def test_symptoms_are_shared_middle_nodes():
    uses = Counter(_symptom(i) for i in INCIDENTS)
    assert len(NODES["Symptom"]) == 6 and set(uses) == set(NODES["Symptom"])
    assert min(uses.values()) >= 2
    for sid, s in NODES["Symptom"].items():
        assert sid == f"sym-{s['kind']}-{s['target_id']}"


def test_payment_archetype_with_varied_resolvers():
    pay = [i for i in INCIDENTS if _cause(i) == "payment" and _symptom(i) == "sym-error_rate-checkout"]
    assert len(pay) >= 8
    resolver = {r["dst"]: r["src"] for r in _rows(B, "RESOLVED")}
    assert len({resolver[i] for i in pay}) >= 3


def test_resolvers_were_present_and_prefer_recent_committers():
    resolver = {r["dst"]: r["src"] for r in _rows(B, "RESOLVED")}
    from_committers = 0
    for iid, pid in resolver.items():
        onset = INCIDENTS[iid]["onset_at"]
        assert ORG.person(pid).active_at(onset)
        cause = _cause(iid)
        if any(c["author_id"] == pid and c["component_id"] == cause and onset - 30 * DAY_MS <= c["at"] < onset
               for c in NODES["Commit"].values()):
            from_committers += 1
    assert from_committers >= 15


def test_one_not_applied_then_applied():
    by_inc = defaultdict(list)
    for r in _rows(B, "RESOLVED_BY") + _rows(B, "ATTEMPTED"):
        by_inc[r["src"]].append(NODES["Action"][r["dst"]])
    assert all(NODES["Action"][r["dst"]]["verdict"] == "APPLIED" for r in _rows(B, "RESOLVED_BY"))
    assert all(NODES["Action"][r["dst"]]["verdict"] != "APPLIED" for r in _rows(B, "ATTEMPTED"))
    mixed = [i for i, acts in by_inc.items() if {a["verdict"] for a in acts} == {"NOT_APPLIED", "APPLIED"}]
    assert len(mixed) == 1
    acts = sorted(by_inc[mixed[0]], key=lambda a: a["at"])
    assert [a["verdict"] for a in acts] == ["NOT_APPLIED", "APPLIED"]
    assert _cause(mixed[0]) == "payment"
    assert all(a["verdict"] == "APPLIED" for i, v in by_inc.items() if i != mixed[0] for a in v)
    kinds = {a["kind"] for v in by_inc.values() for a in v}
    assert kinds == {"flip_flag", "rollback_deploy", "data_repair", "open_issue"}


def test_postmortems_varied_and_linked():
    pms = NODES["Postmortem"].values()
    assert len({p["summary"] for p in pms}) == 40
    for p in pms:
        assert p["url"] == f"docs/postmortems/{p['id']}.md"
        assert 2 <= p["summary"].count(". ") + 1 <= 3
        assert _cause(p["incident_id"]) in p["summary"]
    openings = {p["summary"].split(" (dep-")[0].split(" dep-")[0][:25] for p in pms}
    assert len(openings) >= 10


def test_files_belong_to_services_or_transforms():
    for r in _rows(B, "PART_OF"):
        path = NODES["File"][r["src"]]["path"]
        assert path.startswith((f"src/{r['dst']}/", "pipeline/transforms/"))
    assert {d for (rel, _, d) in B.edges if rel == "PART_OF"} == {"Service", "Transform"}
