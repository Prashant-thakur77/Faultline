"""Committed healthy observability baselines (pipeline/baselines/*.json, produced by the existing
`make baselines`) → graph telemetry the agent reasons over:

* (:MetricWindow {metric:'revenue_usd', day, value})-[:WINDOW_OF]->(:Table marts.fct_revenue) per baseline day
* (:Baseline {column, min, max, mean_lo, mean_hi, days})-[:BASELINE_OF]->(:Column) per profiled numeric column
Data tools read these through RO templates (Q-BASE-1/2); nothing reads the JSON at runtime.
"""

from __future__ import annotations

import json

from ..config import settings
from .bundle import Bundle

FACT = "marts.fct_revenue"
SCHEMA_OF = {"stg_orders": "staging", "stg_customers": "staging", "stg_fx_rates": "staging"}


def build(tenant: str = "acme") -> Bundle:
    b = Bundle()
    daily = json.loads((settings.baselines_dir / "daily_revenue_baseline.json").read_text())
    for r in daily:
        wid = f"mw-{FACT}-revenue_usd-{r['day']}"
        b.node("MetricWindow", wid, tenant=tenant, target_id=FACT, metric="revenue_usd", day=r["day"],
               value=float(r["revenue_usd"]), order_count=int(r.get("order_count") or 0), kind="baseline")
        b.edge("WINDOW_OF", "MetricWindow", wid, "Table", FACT)
    prof = json.loads((settings.baselines_dir / "profile_baseline.json").read_text())
    for short, spec in prof.items():
        table = f"{SCHEMA_OF.get(short, 'staging')}.{short}"
        days = spec.get("per_day", [])
        cols = sorted({k[: -len("_min")] for d in days for k in d if k.endswith("_min")})
        for col in cols:
            mins = [d[f"{col}_min"] for d in days if d.get(f"{col}_min") is not None]
            maxs = [d[f"{col}_max"] for d in days if d.get(f"{col}_max") is not None]
            means = [d[f"{col}_mean"] for d in days if d.get(f"{col}_mean") is not None]
            if not mins or not maxs:
                continue
            bid = f"base-{table}.{col}"
            b.node("Baseline", bid, tenant=tenant, column=f"{table}.{col}", table=table, min=float(min(mins)),
                   max=float(max(maxs)), mean_lo=float(min(means)) if means else None,
                   mean_hi=float(max(means)) if means else None, days=len(days))
            b.edge("BASELINE_OF", "Baseline", bid, "Column", f"{table}.{col}")
    return b
