"""Service domain (OpenTelemetry Demo topology) → Bundle.

CALLS client→server carries the traffic matrix (rps). Failure flows server→client:
PROPAGATES_TO {cap = criticality, rps, cut_cost = traffic share × tier weight of the client}.
Flags GATE services/endpoints (control plane, cap 1.0).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..agent.weights import tier_weight, weights
from .bundle import Bundle
from .lineage_to_graph import flow

TOPOLOGY = Path(__file__).resolve().parents[3] / "data" / "topology" / "otel-demo.yaml"


def load_topology(path: Path = TOPOLOGY) -> dict:
    return yaml.safe_load(path.read_text())


def build(path: Path = TOPOLOGY) -> Bundle:
    topo = load_topology(path)
    tenant = topo["tenant"]
    entry_rps = float(weights()["impact"]["entry_rps"])
    b = Bundle()
    labels: dict[str, str] = {}
    tiers: dict[str, int] = {}
    for s in topo["services"]:
        b.node("Service", s["id"], tenant=tenant, name=s["name"], lang=s["lang"], tier=s["tier"],
               revenue_path=s["revenue_path"], status="active", entry=(s["id"] == topo["entry"]))
        labels[s["id"]], tiers[s["id"]] = "Service", s["tier"]
    for d in topo["datastores"]:
        b.node("Datastore", d["id"], tenant=tenant, name=d["name"], kind=d["kind"], tier=1)
        labels[d["id"]], tiers[d["id"]] = "Datastore", 1
    for c in topo["calls"]:
        cl, sv = c["client"], c["server"]
        b.edge("CALLS", labels[cl], cl, labels[sv], sv, rps=c["rps"], err_rate=0.0, p99_ms=0.0)
        if c["cap"] > 0:
            cut_cost = (c["rps"] / entry_rps) * tier_weight(tiers[cl])
            flow(b, labels[sv], sv, labels[cl], cl, c["cap"], cut_cost, "service", rps=c["rps"],
                 via_endpoint=c.get("endpoint", ""), cap_why=c.get("why", "synchronous call; errors propagate"))
    for e in topo["endpoints"]:
        b.node("Endpoint", e["id"], tenant=tenant, service_id=e["service"], route=e["route"], protocol=e["protocol"])
        b.edge("EXPOSES", "Service", e["service"], "Endpoint", e["id"])
    for f in topo["flags"]:
        cuts = f.get("cuts") or [None, None]
        b.node("FeatureFlag", f["id"], tenant=tenant, key=f["id"], state=f["state"], note=f.get("note", ""),
               cuts_src=cuts[0], cuts_dst=cuts[1])
        target = f["gates"]
        tlabel = "Endpoint" if ":" in target else labels[target]
        b.edge("GATES", "FeatureFlag", f["id"], tlabel, target, cap=1.0, w=1)
    return b
