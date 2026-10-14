"""Code specialist: what the graph knows about each suspect's code (diff_summary, Q-CODE-1).

Honest by construction: Faultline has no real code graph. The graph holds, per change, the commits it CONTAINS, the
files they TOUCH, the component each file is PART_OF, the PRs holding those commits, commit authorship and the typed
facts a diff ASSERTS. It does not hold diff text or functions, and file paths are synthetic. So this specialist:

* names a suspect only when that code lands on the component the change CHANGED (a commit's file is PART_OF it, or an
  asserted fact is ABOUT it), decided by the query (code_on_target / facts_on_target);
* reports `insufficient` when no suspect carries any commit or fact (common for injected and config changes), and
  lists each such change in `unknowns`;
* always states the limits below in its contract.
"""

from __future__ import annotations

from ..contracts import obs, ref
from .base import Specialist, SpecialistCtx

LIMITS = [
    "no function-level code graph: a file path is the finest grain, and the paths are synthetic",
    "no diff text: only the commits a change CONTAINS, the files they TOUCH (PART_OF a component), PRs, authors and "
    "the typed facts it ASSERTS",
    "a change with no commits or facts in the graph (most injected and config changes) cannot be inspected",
]


class CodeSpecialist(Specialist):
    role = "code"
    limits = LIMITS

    async def run(self, ctx: SpecialistCtx):
        evidence, named, unknowns, examined = [], [], [], 0
        if not ctx.suspects:
            unknowns.append("no upstream change in the window")
        for s in ctx.suspects:
            args = {"deploy_id": s["id"]}
            r = await ctx.call("diff_summary", args)
            if "error" in r or not r.get("rows"):
                unknowns.append(f"diff_summary {s['id']}: {str(r.get('error') or 'no record')[:160]}")
                continue
            row = r["rows"][0]
            if not r.get("inspectable"):
                evidence.append(ref(r, "diff_summary", args, [obs("id", row["id"]), obs("commits", row["commits"])]))
                unknowns.append(f"{s['id']}: no commits, PR or diff facts in the graph; its code cannot be inspected")
                continue
            examined += 1
            o = [obs("id", row["id"]), obs("target", row.get("target")), obs("code_on_target", row["code_on_target"]),
                 obs("facts_on_target", row["facts_on_target"])]
            o += [obs("authors", a) for a in row["authors"][:5]] + [obs("prs", p) for p in row["prs"][:3]]
            evidence.append(ref(r, "diff_summary", args, o))
            if row["code_on_target"] or row["facts_on_target"]:
                named.append(s["id"])
            else:
                unknowns.append(f"{s['id']}: its code lands on {sorted(set(row['file_components'])) or 'no component'}, "
                                f"not on the component it CHANGED ({row.get('target')})")
        return self.report(ctx, evidence=evidence, suspect_ids=named, unknowns=unknowns, complete=examined > 0)
