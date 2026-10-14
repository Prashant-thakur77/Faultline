"""Live: the load-bearing templates on the seeded acme graph give the designed answers
(docs/design/scenario_numbers.md). Needs `make up && make seed`."""

import pytest

from faultline.graph.algo.maxflow import min_cut
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ro(db):
    r = RO("acme")
    try:
        r.require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"acme not seeded: {e}")
    return r


def test_gate_path_exists_for_real_cause_and_not_for_off_path_change(ro):
    assert ro.run("Q-GATE-1", {"cause": "payment", "symptom": "checkout"}).rows[0]["chain"] == ["payment", "checkout"]
    assert ro.run("Q-GATE-1", {"cause": "recommendation", "symptom": "checkout"}).rows == []  # no path, no claim


def test_gate_flow_bounds(ro):
    flow = lambda srcs, sym: ro.run("Q-GATE-3", {"sources": srcs, "symptom": sym}).rows[0]["max_flow"]  # noqa: E731
    assert flow(["payment"], "checkout") == pytest.approx(1.0)
    assert flow(["email"], "checkout") == pytest.approx(0.02)           # path exists, cannot carry the impact
    assert flow(["raw.raw_fx_rates"], "kpi.exec_revenue") == pytest.approx(0.0692)
    assert flow(["payment"], "kpi.exec_revenue") == pytest.approx(1.0)  # cross-domain service → lineage


def test_cross_domain_path_to_kpi(ro):
    chain = ro.run("Q-GATE-1", {"cause": "payment", "symptom": "kpi.exec_revenue"}).rows[0]["chain"]
    assert chain[0] == "payment" and chain[-1] == "kpi.exec_revenue" and "raw.raw_orders" in chain


def test_two_target_min_cut_is_service_flag_plus_data_quarantine(ro):
    flow = ro.run("Q-CUT-1", {"failing": "payment", "protect": ["frontend-proxy", "kpi.exec_revenue"]}).rows[0]
    cand = ro.run("Q-CUT-2", {"failing": "payment"}).rows
    edges = [(e["u"], e["v"], f"{e['u']}>{e['v']}") for e in cand]
    cap = {f"{e['u']}>{e['v']}": float(e["cut_cost"]) for e in cand}
    fl = {f"{u}>{v}": float(f) for (u, v), f in zip(flow["flow_edges"], flow["flows"])}
    # the protected targets are sinks: drop edges leaving them so the cut separates source from targets
    cut, _ = min_cut({"payment"}, edges, cap, fl, float(flow["max_flow"]), targets={"frontend-proxy", "kpi.exec_revenue"})
    assert sorted((u, v) for u, v, _ in cut) == [("payment", "checkout"), ("payment", "raw.raw_orders")]


def test_blast_radius_and_scope(ro):
    blast = {r["id"] for r in ro.run("Q-BLAST-1", {"id": "payment"}).rows}
    assert {"checkout", "frontend", "frontend-proxy", "kpi.exec_revenue"} <= blast
    scope = {r["id"] for r in ro.run("Q-LIN-1", {"symptom": "kpi.exec_revenue"}).rows}
    assert {"raw.raw_orders", "raw.raw_fx_rates", "payment"} <= scope


def test_chokepoints_deterministic(ro):
    a = ro.run("Q-CHOKE-1", {}).rows
    assert a == ro.run("Q-CHOKE-1", {}).rows and a[0]["id"] == "frontend"
