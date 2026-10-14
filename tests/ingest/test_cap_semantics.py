"""cap semantics (docs/design/scenario_numbers.md §1): criticality for services, end-to-end row
share for lineage. Never a traffic share."""

import json
from pathlib import Path

import yaml

from faultline.ingest import cross_domain, lineage_to_graph, otel_topology

ROOT = Path(__file__).resolve().parents[2]


def _flows(b):
    return {(r["src"], r["dst"]): r["props"] for (rel, _, _), rows in b.edges.items() if rel == "PROPAGATES_TO" for r in rows}


def test_service_caps_are_criticality_with_reasons():
    topo = yaml.safe_load((ROOT / "data/topology/otel-demo.yaml").read_text())
    for c in topo["calls"]:
        assert c["cap"] in (0.0, 0.02, 1.0), c
        if c["cap"] < 1.0:
            assert c.get("why"), f"best-effort cap needs a reason: {c}"
    flows = _flows(otel_topology.build())
    assert flows[("payment", "checkout")]["cap"] == 1.0
    assert flows[("email", "checkout")]["cap"] == 0.02
    assert all(0.0 <= p["cap"] <= 1.0 for p in flows.values())


def test_every_propagates_has_a_reverse_depends_on():
    for b in (otel_topology.build(), lineage_to_graph.build(), cross_domain.build()):
        prop = {(r["src"], r["dst"]) for (rel, _, _), rows in b.edges.items() if rel == "PROPAGATES_TO" for r in rows}
        dep = {(r["dst"], r["src"]) for (rel, _, _), rows in b.edges.items() if rel == "DEPENDS_ON" for r in rows}
        assert prop == dep


def test_lineage_row_share_matches_committed_sql_provenance():
    prov = json.loads((ROOT / "data/fixtures/lineage/provenance.json").read_text())
    flows = _flows(lineage_to_graph.build())
    fx = flows[("staging.stg_fx_rates", "marts.fct_revenue")]["cap"]
    assert fx == max(prov["fx_row_share"].values())
    others = [p["cap"] for k, p in flows.items() if k != ("staging.stg_fx_rates", "marts.fct_revenue")]
    assert all(c == 1.0 for c in others), "upstream lineage edges must be 1.0 (end-to-end row share)"


def test_cross_domain_payment_emits_raw_orders():
    flows = _flows(cross_domain.build())
    assert flows[("payment", "raw.raw_orders")]["domain"] == "cross"
