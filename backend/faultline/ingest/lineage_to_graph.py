"""Data-lineage domain → Bundle (source: data/fixtures/lineage/*.json).

Nodes: Table (name for full-text), Column, Transform, KPI, Dashboard.
Edges: OF, READS, WRITES, DERIVES_FROM, COMPUTED_FROM, SHOWS, plus the failure-flow layer
PROPAGATES_TO (input → output, cap = end-to-end row share) and its reverse DEPENDS_ON.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..agent.weights import weights
from .bundle import Bundle

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "lineage"


def _load(name: str):
    return json.loads((FIXTURE / name).read_text())


def flow(b: Bundle, src_label: str, src: str, dst_label: str, dst: str, cap: float, cut_cost: float,
         domain: str, **extra) -> None:
    """Materialise one failure-flow edge and its reverse."""
    props = {"cap": float(cap), "w": 1, "cut_cost": round(float(cut_cost), 4), "domain": domain, **extra}
    b.edge("PROPAGATES_TO", src_label, src, dst_label, dst, **props)
    b.edge("DEPENDS_ON", dst_label, dst, src_label, src, **props)


def build(tenant: str = "acme") -> Bundle:
    b = Bundle()
    data_tier = weights()["impact"]["data_tier_weight"]
    for t in _load("tables.json"):
        b.node("Table", t["id"], tenant=tenant, name=t["name"].replace("_", " "), table=t["name"], layer=t["layer"], doc=t["doc"],
               tags=t["tags"], row_count=t["row_count"], tier=1)
    for c in _load("columns.json"):
        b.node("Column", c["id"], tenant=tenant, name=c["name"], table_id=c["table_id"], dtype=c["dtype"], doc=c["doc"])
        b.edge("OF", "Column", c["id"], "Table", c["table_id"])
    for tr in _load("transforms.json"):
        b.node("Transform", tr["id"], tenant=tenant, path=tr["path"], kind=tr["kind"], name=tr["id"])
        b.edge("WRITES", "Transform", tr["id"], "Table", tr["writes"])
        for r in sorted(set(tr["reads"])):
            b.edge("READS", "Transform", tr["id"], "Table", r)
        # a change to a transform propagates to the table it writes
        flow(b, "Transform", tr["id"], "Table", tr["writes"], 1.0, data_tier, "data")
    for e in _load("table_lineage.json"):
        flow(b, "Table", e["src"], "Table", e["dst"], e["cap"], e["cap"] * data_tier, "data",
             transform=e["transform"], cap_why=e["cap_why"])
    for e in _load("column_lineage.json"):
        b.edge("DERIVES_FROM", "Column", e["dst"], "Column", e["src"], transform_id=e["transform"],
               key=f"{e['transform']}")
    for k in _load("kpis.json"):
        b.node("KPI", k["id"], tenant=tenant, name=k["name"], unit=k["unit"], doc=k["doc"], tier=1)
        b.edge("COMPUTED_FROM", "KPI", k["id"], "Table", k["computed_from"])
        flow(b, "Table", k["computed_from"], "KPI", k["id"], 1.0, data_tier, "data")
    for d in _load("dashboards.json"):
        b.node("Dashboard", d["id"], tenant=tenant, name=d["name"])
        b.edge("SHOWS", "Dashboard", d["id"], "KPI", d["shows"])
        flow(b, "KPI", d["shows"], "Dashboard", d["id"], 1.0, data_tier, "data")
    return b
