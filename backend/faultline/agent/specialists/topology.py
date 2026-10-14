"""Topology specialist: which suspects have a causal path to which symptoms (algo.SPpaths, Q-GATE-1).

Names a suspect when the graph returns at least one CHANGED|GATES|PROPAGATES_TO path from it to a symptom. It only
describes reachability; whether the path is sufficient (G5) or the earliest (G3) is the gate's call."""

from __future__ import annotations

from ..contracts import obs, ref
from .base import Specialist, SpecialistCtx


class TopologySpecialist(Specialist):
    role = "topology"
    limits = ["reachability only: a path is necessary for a claim, never sufficient (flow and timing are gate checks)"]

    async def run(self, ctx: SpecialistCtx):
        evidence, named, unknowns = [], [], []
        symptoms = list(ctx.packet.get("symptoms") or [])
        if not ctx.suspects:
            unknowns.append("no upstream change in the window to trace")
        for s in ctx.suspects:
            for sym in symptoms:
                args = {"from_id": s["id"], "to_id": sym}
                out = await ctx.call("causal_paths", args)
                if "error" in out:
                    unknowns.append(f"causal_paths {s['id']} → {sym}: {str(out['error'])[:160]}")
                    continue
                rows = out.get("rows") or []
                evidence.append(ref(out, "causal_paths", args, [obs("chain", rows[0]["chain"])] if rows else []))
                if rows and s["id"] not in named:
                    named.append(s["id"])
                if not rows:
                    unknowns.append(f"no path {s['id']} → {sym}")
        return self.report(ctx, evidence=evidence, suspect_ids=named, unknowns=unknowns)
