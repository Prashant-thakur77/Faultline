"""Obligations (M12 obligation clock) → Bundle: who we would be failing, and what we promised them.

* (:SLO {id, objective, metric, window_days, budget, spent_prior, tier})-[:FOR]->(:Service), one per tier-1 and
  tier-2 service, objective by tier from the spec's `slo_policy`. `budget` = 1 − objective (the error ratio the
  window may spend); `spent_prior` = the share of that budget already spent earlier in the window, before the
  graph's telemetry horizon, drawn deterministically per SLO (random.Random(f"{seed}:{slo id}")).
* (:Customer {id, name, tier, mrr})-[:CONSUMES {via}]->(entry service, API service or KPI), from the spec's
  `customers` list. Everything is synthetic and says so in its name.

Pure and deterministic: no FalkorDB access, no wall clock. The burn rate, budget remaining and customers reached
are computed at incident time in Cypher (Q-OBL-SLO, Q-OBL-CUST); the time to breach in code (weights.yaml
`obligation`).
"""

from __future__ import annotations

import random
from typing import Any

from .bundle import Bundle
from .otel_topology import TOPOLOGY, load_topology


def slo_id(service_id: str) -> str:
    """Graph id of a service's SLO (prefixed so it can never collide with a component id)."""
    return f"slo-{service_id}"


def build_from(spec: dict[str, Any], services: list[dict[str, Any]], labels: dict[str, str], tenant: str,
               seed: int = 42) -> Bundle:
    """`services`: [{id, tier}] of the tenant's Service nodes; `labels`: node id → label of every node a customer
    may consume (CONSUMES targets must exist, so a typo fails the seed instead of dropping an edge)."""
    policy = spec["slo_policy"]
    objective_by_tier = {int(k): float(v) for k, v in policy["objective_by_tier"].items()}
    lo, hi = (float(x) for x in policy["spent_prior"])
    if not 0.0 <= lo <= hi < 1.0:
        raise ValueError("slo_policy.spent_prior must be a range inside [0, 1)")
    b = Bundle()
    for s in sorted(services, key=lambda x: x["id"]):
        objective = objective_by_tier.get(int(s.get("tier") or 3))
        if objective is None:
            continue
        sid = slo_id(s["id"])
        spent = round(random.Random(f"{seed}:{sid}").uniform(lo, hi), 3)
        b.node("SLO", sid, tenant=tenant, objective=objective, metric=policy["metric"],
               window_days=int(policy["window_days"]), budget=round(1.0 - objective, 6), spent_prior=spent,
               tier=int(s["tier"]), name=f"{s['id']} error-rate SLO {objective:.0%} over {int(policy['window_days'])} days",
               synthetic=True)
        b.edge("FOR", "SLO", sid, "Service", s["id"])
    seen: set[str] = set()
    for c in spec.get("customers") or []:
        if c["id"] in seen:
            raise ValueError(f"duplicate customer id {c['id']!r}")
        seen.add(c["id"])
        if "(synthetic" not in c["name"]:
            raise ValueError(f"customer {c['id']!r}: the name must say it is synthetic")
        b.node("Customer", c["id"], tenant=tenant, name=c["name"], tier=int(c["tier"]), mrr=float(c["mrr"]),
               synthetic=True)
        for x in c["consumes"]:
            if x["node"] not in labels:
                raise ValueError(f"customer {c['id']!r} consumes unknown node {x['node']!r}")
            b.edge("CONSUMES", "Customer", c["id"], labels[x["node"]], x["node"], via=x["via"])
    return b


def build(seed: int = 42) -> Bundle:
    """acme: SLOs over the OTel Demo services, customers on its entry points and the revenue KPI."""
    import json

    from .org_gen import LINEAGE_DIR

    topo = load_topology(TOPOLOGY)
    labels = {s["id"]: "Service" for s in topo["services"]}
    labels.update({k["id"]: "KPI" for k in json.loads((LINEAGE_DIR / "kpis.json").read_text())})
    return build_from(topo, topo["services"], labels, topo["tenant"], seed)
