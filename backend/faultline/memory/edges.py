"""Memory that changes the answer (M15 #4): a verified fix can teach the graph a failure link it was missing.

When the gate abstains because the graph has no path from a change to the symptom, the incident does not end there:
a human can name the change they believe caused it (`human_fix_option`), and that rollback goes through the same
two-step approval and three-valued verification as any action. If it verifies APPLIED (GitHub main + the symptom
back in band), the graph was demonstrably missing a link: `propose` reads the gap in FalkorDB (Q-LEARN-GAP: no
PROPAGATES_TO path from the changed component to the symptom, and the measured share the link carried) and records
an EdgeProposal. Nothing reads a proposal as an edge. A human approves the exact proposal (plan hash); only then is a
`PROPAGATES_TO {learned: true}` pair written (graph/writes.py::approve_edge, one query), and the next incident on that
path can be proved. The gate is unchanged: a learned edge is an edge, named in the proof path, with its incident.
"""

from __future__ import annotations

from ..actions import act
from ..agent.weights import weights
from ..graph import writes


def human_fix_option(c: act.Ctx, *, change: str, by: str, why: str) -> dict:
    """An enabled rollback of a change a HUMAN named after the gate did not confirm one. It is recorded as a plan
    option like any other (choose → approve plan hash → execute → verify); its reason says the gate did not confirm it."""
    from ..agent.state import Stage, ordinal

    inc = (c.ro().run("Q-INC-1", {"inc": c.inc}).rows or [{}])[0]
    if inc.get("confident"):  # the gate confirmed a cause: its own options stand
        raise ValueError(f"{c.inc} has a confirmed cause; a human-named fix is for an incident the gate did not confirm")
    onset = int(inc.get("onset_at") or 0)
    window = {r["deploy"] for r in c.ro().run("Q-SUS-2", {"onset": onset, "window_ms": 30 * 60_000}).rows}
    if change not in window:  # only a change that landed in this incident's 30-minute window
        raise ValueError(f"{change} did not land in {c.inc}'s 30-minute window before onset")
    if not c.ro().run("Q-PERSON-1", {"person": by}).rows:
        raise ValueError(f"{by!r} is not an active person in this tenant's graph")
    # escalated to a human; accepted without confidence (stage GATE: no plan was made); or awaiting approval. Never a
    # resolved, no-incident or failed one. (GATE was added after the first learning-eval run, where 6 not-confident
    # incidents could not take a human fix: DECISIONS 2026-10-13, M15 #4.)
    takeover = (Stage.UNKNOWN_ESCALATED.value, Stage.GATE.value)
    if inc.get("stage") not in takeover + (Stage.AWAITING_APPROVAL.value,):
        raise ValueError(f"{c.inc} is {inc.get('stage')}: a human fix is for an incident the gate escalated, accepted "
                         "without confidence, or is awaiting approval on")
    detail = c.ro().run("Q-CHANGE-2", {"id": change}).rows
    if not detail or detail[0]["kind"] not in ("deploy", "config"):
        raise ValueError(f"{change} is not a deploy or config change in this incident's graph")
    n = 1 + sum(1 for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"].startswith(f"act-{c.inc}-h"))
    aid = f"act-{c.inc}-h{n}"
    args = {"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": detail[0]["target"], "revert": change,
            "reviewers": []}
    reason = (f"named by {by} after the gate did not confirm a cause: {why[:200]} (the gate has not confirmed {change}; "
              "verification decides whether this fixed it)")
    writes.record_option(c.g(), inc=c.inc, aid=aid, kind="rollback_deploy", option=f"roll back {change} (human-named)",
                         enabled=True, reason=reason, target=change, preview=args)
    if inc["stage"] in takeover:  # the human took it over: open it for approval of this exact rollback
        writes.advance_stage(c.g(), inc=c.inc, run=c.run, stage=Stage.AWAITING_APPROVAL.value,
                             ord_=ordinal(Stage.AWAITING_APPROVAL), force=inc["stage"] == Stage.UNKNOWN_ESCALATED.value,
                             note=f"{by} took over the {inc['stage'].lower().replace('_', ' ')} incident and named {change}")
    return {"id": aid, "kind": "rollback_deploy", "target": change, "reason": reason, "args": args}


def propose(c: act.Ctx, aid: str, *, onset_ms: int, symptoms: list[str]) -> list[dict]:
    """After a VERIFIED (APPLIED) rollback: one EdgeProposal per symptom the rolled-back change's component has no path
    to, carrying the measured share. Any other action, or any other verdict, proposes nothing."""
    a = next((x for x in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if x["id"] == aid), None)
    if a is None or a["kind"] != "rollback_deploy" or a["verdict"] != "APPLIED":
        return []
    import json

    change = json.loads(a["spec"])["args"]["revert"]
    iw = weights()["intake"]
    rows = c.ro().run("Q-LEARN-GAP", {"change": change, "symptoms": sorted(set(symptoms)), "since": onset_ms,
                                      "until": onset_ms + 10 * 60_000,
                                      "base_since": onset_ms - int(iw["baseline_min"]) * 60_000,
                                      "base_until": onset_ms - int(iw["baseline_gap_min"]) * 60_000}).rows
    from ..agent.datatools import band_from, in_band

    def anomalous(base, peak, vals) -> bool:  # verification's own band rule (no learning from noise)
        vals = [float(v) for v in vals or []]
        return bool(vals) and peak is not None and not in_band(float(peak), float(base), band_from(vals))

    out = []
    for r in rows:
        if r["has_path"] or r["share"] is None:
            continue
        if not (anomalous(r["obase"], r["opeak"], r["obase_vals"]) and anomalous(r["sbase"], r["speak"], r["sbase_vals"])):
            continue  # both ends must have been out of band in this incident, or the measured share is noise
        why = (f"rolling back {change} brought {r['symptom']} back in band (verified {aid}), but the graph had no path "
               f"from {r['origin']}; measured share {float(r['share']):.3f} (symptom excess {float(r['symptom_excess']):.4f} "
               f"/ component excess {float(r['origin_excess']):.4f})")
        out.append(writes.propose_edge(c.g(), inc=c.inc, src=r["origin"], dst=r["symptom"], cap=float(r["share"]),
                                       aid=aid, change=change, why=why) | {"why": why})
    return out


def approve(c: act.Ctx, pid: str, plan_hash: str, by: str) -> bool:
    return writes.approve_edge(c.g(), pid=pid, plan_hash=plan_hash, by=by)


__all__ = ["approve", "human_fix_option", "propose"]
