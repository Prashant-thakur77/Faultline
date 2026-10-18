"""Data specialist: the warehouse and pipeline tools (the system under observation), for KPI/data symptoms.

KPI vs its baseline (get_metric_history, compare_to_baseline), then the anomalous-row share of every baselined column
of the tables upstream of the symptom (anomalous_row_share). Which measurement is anomalous is read back from the
graph (Evidence.anomalous via Q-EV-1, decided in code when it was recorded). It names a suspect whose CHANGED
target has a causal path (causal_paths, Q-GATE-1) to a table it measured anomalous."""

from __future__ import annotations

from ...graph.ro import RO
from ..contracts import obs, ref
from .base import Specialist, SpecialistCtx

_ROW_FIELDS = ("table", "column", "day", "rows", "outside", "share")


class DataSpecialist(Specialist):
    role = "data"
    limits = ["warehouse measurements only: daily KPI and per-column baseline ranges; no row-level lineage of a change"]

    async def run(self, ctx: SpecialistCtx):
        evidence, unknowns = [], []
        nodes = ctx.packet.get("symptom_nodes") or []
        if not any(n.get("label") == "KPI" for n in nodes):
            return self.report(ctx, evidence=[], suspect_ids=[],
                               unknowns=["no KPI symptom: the data channel has nothing to measure for this incident"])
        scope_tables = sorted({n["id"] for n in ctx.packet.get("scope") or [] if n.get("label") == "Table"})
        kpi_day = None
        m = await ctx.call("get_metric_history", {})
        if m.get("evidence_id"):
            met = m.get("metric") or {}
            evidence.append(ref(m, "get_metric_history", {}, [obs(k, met.get(k)) for k in ("kpi_day", "revenue", "anomaly_ratio")
                                                             if k in met]))
            kpi_day = met.get("kpi_day")
        else:
            unknowns.append(f"get_metric_history: {str(m.get('error'))[:160]}")
        c = await ctx.call("compare_to_baseline", {"last_days": 7})
        if c.get("evidence_id"):
            evidence.append(ref(c, "compare_to_baseline", {"last_days": 7}))
        else:
            unknowns.append(f"compare_to_baseline: {str(c.get('error'))[:160]}")
        tables_measured: list[str] = []
        if scope_tables and kpi_day:
            symptoms = list(ctx.packet.get("symptoms") or [])
            await ctx.call("upstream_scope", {"symptom_id": symptoms[0]})  # ground the scope in this run's results
            bc = await ctx.call("baseline_columns", {"tables": scope_tables})  # recorded: what the channel could measure
            if bc.get("evidence_id"):
                evidence.append(ref(bc, "baseline_columns", {"tables": scope_tables}))
            else:
                unknowns.append(f"baseline_columns: {str(bc.get('error'))[:160]}")
            for col in bc.get("rows") or []:
                args = {"table": col["table"], "column": col["name"], "day": kpi_day}
                r = await ctx.call("anomalous_row_share", args)
                if r.get("evidence_id"):
                    evidence.append(ref(r, "anomalous_row_share", args, [obs(k, r.get(k)) for k in _ROW_FIELDS]))
                    tables_measured.append(col["table"])
                else:
                    unknowns.append(f"anomalous_row_share {col['table']}.{col['name']}: {str(r.get('error'))[:160]}")
        elif not scope_tables:
            unknowns.append("no table upstream of the symptom")
        # which of this run's measurements are anomalous: read back from the graph, not recomputed here. A documented
        # non-evidence read: Q-EV-1 re-reads Evidence this specialist already recorded (its anomalous flag), no new fact
        ids = [e.evidence_id for e in evidence if e is not None]
        hot = sorted({a for r in (RO(ctx.run.tenant, ctx.run.graph).run("Q-EV-1", {"ids": ids}).rows if ids else [])
                      if r["anomalous"] and r["kind"] == "row_share" for a in r["about"] if a in set(tables_measured)})
        named = []
        for s in ctx.suspects:
            for t in hot:
                args = {"from_id": s["id"], "to_id": t}
                p = await ctx.call("causal_paths", args)
                if p.get("rows"):
                    evidence.append(ref(p, "causal_paths", args, [obs("chain", p["rows"][0]["chain"])]))
                    named.append(s["id"])
                    break
        if not hot and evidence:
            unknowns.append("no measured table is outside its baseline range")
        return self.report(ctx, evidence=evidence, suspect_ids=named, unknowns=unknowns)
