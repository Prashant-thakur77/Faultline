"""Change specialist: what each upstream change in the window is, as the graph records it (change_details, Q-CHANGE-2),
and which active decisions its asserted facts violate (decision_check, Q-DEC-1).

It DESCRIBES changes and does not judge them: it names every suspect whose change record it could read (kind, time,
the component it CHANGED). Gate G7 then asks whether the code or data channel independently names the same Deploy."""

from __future__ import annotations

from ..contracts import obs, ref
from .base import Specialist, SpecialistCtx


class ChangeSpecialist(Specialist):
    role = "change"
    limits = ["change records only (kind, time, actor, title, CHANGED target, asserted facts); no rollout progress or canary data"]

    async def run(self, ctx: SpecialistCtx):
        evidence, named, unknowns = [], [], []
        if not ctx.suspects:
            unknowns.append("no upstream change in the window")
        for s in ctx.suspects:
            args = {"deploy_id": s["id"]}
            d = await ctx.call("change_details", args)
            if "error" in d or not d.get("rows"):
                unknowns.append(f"change_details {s['id']}: {str(d.get('error') or 'no record')[:160]}")
                continue
            row = d["rows"][0]
            evidence.append(ref(d, "change_details", args, [obs("id", row["id"]), obs("kind", row.get("kind")),
                                                            obs("target", row.get("target")), obs("at", row.get("at"))]))
            if row.get("target"):
                named.append(s["id"])
            dargs = {"change_id": s["id"]}
            dc = await ctx.call("decision_check", dargs)
            if "error" in dc:
                unknowns.append(f"decision_check {s['id']}: {str(dc['error'])[:160]}")
                continue
            evidence.append(ref(dc, "decision_check", dargs,
                                [obs("decision", r["decision"]) for r in dc.get("rows") or [] if r.get("violated")]))
        return self.report(ctx, evidence=evidence, suspect_ids=named, unknowns=unknowns)
