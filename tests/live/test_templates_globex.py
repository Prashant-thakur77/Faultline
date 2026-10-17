"""Live: the load-bearing templates and graph tools run unchanged on the generated scale tenant globex and give
sensible, structurally checked answers. Needs `make up && make seed TENANT=globex`.

Expected values come from the generator's own output (faultline.ingest.globex), never from hand-typed numbers
that would drift when the spec is tuned."""

from __future__ import annotations

from collections import Counter

import pytest

from faultline.graph.algo.maxflow import min_cut
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO
from faultline.ingest import globex
from faultline.ingest.clock import ANCHOR_MS, DAY_MS
from faultline.ingest.globex import history as gx_history
from faultline.ingest.globex import topology as gx_topology
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
NOW = ANCHOR_MS
SINCE = ANCHOR_MS - 30 * DAY_MS


@pytest.fixture(scope="module")
def ro(db):
    r = RO("globex")
    try:
        r.require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"globex not seeded: {e}")
    return r


@pytest.fixture
def bound(ro):
    tok = context.bind("globex", record=False)
    yield T.TOOLS
    context.unbind(tok)


def _hist_rows(rel):
    return [r for (t, _, _), rows in gx_history.build().edges.items() if t == rel for r in rows]


def test_scale_counts(ro):
    row = ro.run("Q-COUNT-1", {}).rows[0]
    assert row["nodes"] >= 5000 and row["edges"] >= 20000
    prot = ro.run("Q-PROTECT-1", {"target": "card-gateway"}).rows
    assert [(r["id"], r["kind"], int(r["total"])) for r in prot] == [("edge-gateway", "entry", 1)]
    assert ro.run("Q-PROTECT-1", {"target": "edge-gateway"}).rows == []          # an entry protects nothing of itself


def test_gate_path_and_no_path(ro):
    chain = ro.run("Q-GATE-1", {"cause": "card-gateway", "symptom": "order-orchestrator"}).rows[0]["chain"]
    assert chain == ["card-gateway", "order-orchestrator"]
    assert ro.run("Q-GATE-1", {"cause": "recommender", "symptom": "order-orchestrator"}).rows == []  # no path, no claim
    deep = ro.run("Q-GATE-1", {"cause": "legacy-cache", "symptom": "edge-gateway"}).rows
    assert deep and deep[0]["chain"][0] == "legacy-cache" and deep[0]["chain"][-1] == "edge-gateway"


def test_gate_flow_is_criticality(ro):
    flow = lambda srcs, sym: ro.run("Q-GATE-3", {"sources": srcs, "symptom": sym}).rows[0]["max_flow"]  # noqa: E731
    assert flow(["card-gateway"], "order-orchestrator") == pytest.approx(1.0)
    assert flow(["recommender"], "storefront-bff") == pytest.approx(0.02)  # best-effort rail: path exists, no impact
    assert flow(["fx-converter"], "pricing") == pytest.approx(1.0)


def test_blast_radius_fits_the_template_limit_everywhere(ro):
    """No component's blast radius is truncated (the scale tenant still answers exactly)."""
    t = gx_topology.generate()
    sizes = {}
    for c in t.components():
        r = ro.run("Q-BLAST-1", {"id": c})
        assert not r.truncated, c
        sizes[c] = len(r.rows)
    assert max(sizes.values()) >= 30  # hubs have wide blast radii …
    assert sorted(sizes.values())[len(sizes) // 2] <= 10  # … most components do not
    ledger = {r["id"] for r in ro.run("Q-BLAST-1", {"id": "ledger-db"}).rows}
    assert {"ledger-service", "card-gateway", "order-orchestrator", "edge-gateway"} <= ledger


def test_containment_cut_matches_max_flow(ro):
    for failing in ("card-gateway", "legacy-cache", "ledger-db"):
        flow = ro.run("Q-CUT-1", {"failing": failing, "protect": ["edge-gateway"]}).rows[0]
        cand = ro.run("Q-CUT-2", {"failing": failing})
        assert not cand.truncated
        edges = [(e["u"], e["v"], f"{e['u']}>{e['v']}") for e in cand.rows]
        cap = {f"{e['u']}>{e['v']}": float(e["cut_cost"]) for e in cand.rows}
        fl = {f"{u}>{v}": float(f) for (u, v), f in zip(flow["flow_edges"], flow["flows"])}
        cut, _ = min_cut({failing}, edges, cap, fl, float(flow["max_flow"]), targets={"edge-gateway"})
        assert cut and sum(cap[e] for _, _, e in cut) == pytest.approx(float(flow["max_flow"]))
    one = ro.run("Q-CUT-1", {"failing": "legacy-cache", "protect": ["edge-gateway"]}).rows[0]
    assert one["max_flow"] > 0


def test_chokepoints_are_deterministic_hubs(ro):
    a = ro.run("Q-CHOKE-1", {}).rows
    assert a == ro.run("Q-CHOKE-1", {}).rows
    indeg = Counter(c.server for c in gx_topology.generate().calls)
    assert a[0]["score"] > 0 and indeg[a[0]["id"]] >= 20  # preferential attachment made it a hub


def test_connectivity_entry_component(ro):
    comps = ro.run("Q-CONN-1", {}).rows
    main = next(c for c in comps if "edge-gateway" in c["members"])
    assert {"card-gateway", "ledger-db", "legacy-cache", "pricing"} <= set(main["members"])


def test_families_are_the_eight_archetypes(ro):
    cause = {r["src"]: r["dst"] for r in _hist_rows("AFFECTED") if r["props"]["role"] == "cause"}
    fams = ro.run("Q-MEM-6", {"inc": "gx-inc-001"}).rows
    assert len(fams) == 8 and fams[0]["mine"]
    for f in fams:
        assert len({cause[i] for i in f["incidents"]}) == 1  # one family = one recurring cause
    assert sorted(f["size"] for f in fams) == sorted(a["count"] for a in globex.load_spec()["archetypes"])


def test_seed_consolidation_wrote_derived_runbooks(ro):
    rows = ro.run("Q-MEM-3", {"ids": ["sym-latency-recommender", "recommender"]}).rows
    assert rows[0]["source"] == "derived" and rows[0]["support"] >= 2
    assert any(r["id"] == "rb-gx-recommender-latency" for r in rows)


def test_recall_vector_plus_shared_symptom(ro):
    rows = ro.run("Q-MEM-1", {"current": "gx-inc-010", "now": NOW, "half_life_ms": 30 * 86_400_000.0,
                              "w_recency": 0.2}).rows
    assert rows and all(r["shared"] for r in rows) and all(r["id"].startswith("gx-inc-") for r in rows)


def test_who_fixes_and_bus_factor(bound):
    who = bound["who_fixes"](target_id="pricing", now=NOW, since=SINCE)
    assert "error" not in who and len(who["rows"]) >= 3
    assert all(r["reasons"] for r in who["rows"][:3])
    assert any("team-pricing" in r["teams"] for r in who["rows"][:3])
    bf = bound["bus_factor"](target_id="pricing")
    assert bf["top_contributor_inactive"] is True and bf["bus_factor"] == 0  # the expert left
    assert bound["bus_factor"](target_id="ledger-service")["bus_factor"] == 1
    assert bound["bus_factor"](target_id="card-gateway")["bus_factor"] >= 2


def test_causal_paths_and_escalation(bound):
    cp = bound["causal_paths"](from_id="legacy-cache", to_id="edge-gateway")
    assert cp["rows"] and cp["rows"][0]["chain"][0] == "legacy-cache"
    esc = bound["escalation_tree"](person_ids=["gx-p-075", "gx-p-124"])
    assert "error" not in esc and esc["rows"]


def test_brain_templates(ro):
    who = ro.run("Q-BRAIN-WHO", {"target": "card-gateway"}).rows
    assert who and who[0]["commits"] >= who[-1]["commits"] and who[0]["teams"]
    gaps = {r["id"]: r for r in ro.run("Q-GAP-1", {}).rows}
    for o in globex.load_spec()["orphans"]:
        assert gaps[o["component"]]["no_owner"] is True
    assert "pricing" in gaps and gaps["pricing"]["no_runbook"]  # no human runbook for the pricing family
    about = {r["id"]: r for r in ro.run("Q-DEC-ABOUT", {"id": "legacy-cache"}).rows}
    assert about["ADR-031"]["status"] == "active" and about["ADR-031"]["superseded_by"] == []
    assert about["ADR-007"]["superseded_by"] == ["ADR-031"]
    head = ro.run("Q-DEC-2", {"id": "ADR-002"}).rows[0]
    assert head["head"] == "ADR-031" and head["depth"] == 2


def test_context_and_lookup(ro):
    ctx = ro.run("Q-CTX-1", {"id": "card-gateway", "now": NOW}).rows[0]
    assert ctx["team"] == "team-billing" and len(ctx["oncall"]) == 1
    assert ctx["runbooks"] == ["rb-gx-card-errors"] and ctx["decisions"] == ["ADR-015"]
    orphan = ro.run("Q-CTX-1", {"id": "partner-api", "now": NOW}).rows[0]
    assert orphan["team"] is None and orphan["oncall"] == []
    assert ro.run("Q-FIND-SERVICE", {"text": "payment*"}).rows[0]["id"] == "card-gateway"
