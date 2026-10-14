"""Telemetry specialist: error rate around onset vs the pre-onset baseline band (metric_window, simulated telemetry).

Measures every alerting service/datastore and every suspect's changed component. Names a suspect whose changed
component was measured anomalous (the band and the absolute floor are decided in code from weights.yaml)."""

from __future__ import annotations

from ..contracts import obs, ref
from .base import Specialist, SpecialistCtx

_FIELDS = ("target", "baseline", "now", "ratio", "band")


class TelemetrySpecialist(Specialist):
    role = "telemetry"
    limits = ["error rate only (no latency, saturation or traces); telemetry is simulated per scenario"]

    async def run(self, ctx: SpecialistCtx):
        evidence, unknowns, hot = [], [], set()
        services = [n["id"] for n in ctx.packet.get("symptom_nodes") or [] if n.get("label") in ("Service", "Datastore")]
        targets = list(dict.fromkeys(services + [s["target"] for s in ctx.suspects if s.get("target")]))
        if not targets:
            unknowns.append("no service or datastore symptom and no suspect component to measure")
        for t in targets:
            args = {"target_id": t, "onset_ms": ctx.packet["onset_ms"]}
            m = await ctx.call("metric_window", args)
            if "error" in m:
                unknowns.append(f"metric_window {t}: {str(m['error'])[:160]}")
                continue
            evidence.append(ref(m, "metric_window", args, [obs(k, m.get(k)) for k in _FIELDS]))
            if m.get("anomalous"):
                hot.add(t)
        named = [s["id"] for s in ctx.suspects if s.get("target") in hot]
        return self.report(ctx, evidence=evidence, suspect_ids=named, unknowns=unknowns)
