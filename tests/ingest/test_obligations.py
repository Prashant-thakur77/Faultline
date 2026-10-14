"""Obligations seed (M12 obligation clock): SLOs per tier-1/tier-2 service and synthetic customers, deterministic,
whitelisted, every CONSUMES target a real node of the same tenant."""

import pytest

from faultline.graph import schema_model as M
from faultline.ingest import lineage_to_graph, obligations, otel_topology
from faultline.ingest.globex import obligations as gobl
from faultline.ingest.globex import topology as gtopo


def _canon(b):
    return ({k: sorted(v, key=lambda r: r["id"]) for k, v in b.nodes.items()},
            {k: sorted(v, key=lambda r: (r["src"], r["dst"])) for k, v in b.edges.items()})


@pytest.mark.parametrize("mod", [obligations, gobl])
def test_deterministic_and_whitelisted(mod):
    a, b = mod.build(), mod.build(42)
    assert _canon(a) == _canon(b)
    assert set(a.nodes) == {"SLO", "Customer"}
    for (rel, sl, dl) in a.edges:
        M.check_rel(rel), M.check_label(sl), M.check_label(dl)


def test_acme_slos_cover_tier_1_and_2_services_with_budgets():
    topo = otel_topology.load_topology()
    want = {s["id"] for s in topo["services"] if s["tier"] in (1, 2)}
    b = obligations.build()
    slos = {r["id"]: r for r in b.nodes["SLO"]}
    assert {e["dst"] for e in b.edges[("FOR", "SLO", "Service")]} == want
    assert len(slos) == len(want)
    for r in slos.values():
        assert r["objective"] == {1: 0.99, 2: 0.98}[r["tier"]]
        assert r["budget"] == pytest.approx(1 - r["objective"])
        assert 0.2 <= r["spent_prior"] <= 0.6 and r["window_days"] == 30 and r["metric"] == "error_rate"
        assert r["synthetic"] is True


def test_acme_customers_are_synthetic_and_consume_real_nodes():
    b = obligations.build()
    real = {n["id"] for rows in otel_topology.build().nodes.values() for n in rows} | \
           {n["id"] for rows in lineage_to_graph.build().nodes.values() for n in rows}
    custs = {r["id"]: r for r in b.nodes["Customer"]}
    assert custs and all("(synthetic" in r["name"] and r["mrr"] > 0 for r in custs.values())
    consumed = [e for (rel, _, _), es in b.edges.items() if rel == "CONSUMES" for e in es]
    assert {e["dst"] for e in consumed} <= real and all(e["props"]["via"] for e in consumed)
    # at least one customer consumes two nodes (the dedup case the clock must count once)
    per = {}
    for e in consumed:
        per.setdefault(e["src"], set()).add(e["dst"])
    assert any(len(v) > 1 for v in per.values())


def test_globex_customers_consume_generated_services():
    topo = gtopo.generate(42)
    b = gobl.build()
    consumed = {e["dst"] for (rel, _, _), es in b.edges.items() if rel == "CONSUMES" for e in es}
    assert consumed <= set(topo.label)
    assert len(b.nodes["SLO"]) == sum(1 for s in topo.services if s["tier"] in (1, 2))


def test_a_bad_spec_fails_loudly():
    spec = {"slo_policy": {"metric": "error_rate", "window_days": 30, "objective_by_tier": {1: 0.99},
                           "spent_prior": [0.2, 0.6]},
            "customers": [{"id": "c1", "name": "Real Corp", "tier": 1, "mrr": 1, "consumes": [{"node": "x", "via": "w"}]}]}
    with pytest.raises(ValueError, match="synthetic"):
        obligations.build_from(spec, [], {"x": "Service"}, "t")
    spec["customers"][0]["name"] = "Real Corp (synthetic)"
    with pytest.raises(ValueError, match="unknown node"):
        obligations.build_from(spec, [], {}, "t")
