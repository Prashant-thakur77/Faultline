"""Root-cause report generated FROM THE GRAPH (Culprit-style schema; the gate decides proven vs inferred).

proven[]   = claims backed by a passed gate check, each with the evidence ids that check cited
inferred[] = claims the gate could not prove (failed or downgrade-only checks), with their basis
mechanism  = the G2 chain (ordered node ids)
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..graph.ro import RO
from .weights import weights


class Proven(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(min_length=0)
    check: str


class Inferred(BaseModel):
    claim: str
    basis: str


class RootCauseReport(BaseModel):
    incident_id: str
    outcome: str
    confident: bool
    cause_id: str | None
    mechanism: list[str]
    proven: list[Proven]
    inferred: list[Inferred]
    contradictions: list[str] = []
    why_alerts_missed_it: dict = {}
    ownership: dict = {}
    residue: dict = {}   # advisory: the confirmed cause explains k of n measured-anomalous components
    remedy: dict = {}    # learned remediation ordering: history line per offered fix (reorders only)
    futures: list = []   # each option's predicted future (Q-FUTURE-1, its own branch) and, once verified, if it came true
    obligations: dict = {}  # obligation clock: SLO burn, time to breach, customers reached, urgency (ROUTE)
    rejected: list[dict]
    evidence: list[dict]


def build(tenant: str, graph: str, incident_id: str, outcome: str) -> RootCauseReport:
    ro = RO(tenant, graph)
    runs = ro.run("Q-INC-GATES", {"inc": incident_id}).rows
    accepted = [r for r in runs if r["passed"] and r["origin"] == "confirm"]
    final = accepted[-1] if accepted else None
    if final is None and outcome == "NO_INCIDENT":
        final = next((r for r in runs if r["passed"] and r["origin"] == "no_incident"), None)
    proven, inferred, contradictions, cited = [], [], [], set()
    chain: list[str] = []
    if final:
        for c in json.loads(final["checks"]):
            if c["passed"] is True:
                proven.append(Proven(claim=f"{c['name']}: {c['detail']}", evidence_ids=c.get("evidence_ids") or [], check=c["name"]))
                cited.update(c.get("evidence_ids") or [])
                if c["name"] == "G2 path":
                    chain = c["detail"].split(" ; ")[0].split(" → ")
            elif c["passed"] is False and c["name"].startswith("G8"):
                contradictions.append(c["detail"])
            elif c["passed"] is False:
                inferred.append(Inferred(claim=f"{c['name']} not established", basis=c["detail"]))
    for r in runs:  # every evidence item any gate run cited (proofs, rejections, negative proofs)
        for c in json.loads(r["checks"]):
            cited.update(c.get("evidence_ids") or [])
    if final is None:  # abstention (S12): the inferred, unconfirmed origin recorded by the loop
        for h in ro.run("Q-HYP-1", {"inc": incident_id}).rows:
            if h["status"] == "unresolved" and (h.get("reason") or "").startswith("inferred:"):
                inferred.append(Inferred(claim=f"inferred origin {h['cause']} (not confirmed by the gate)",
                                         basis=h["reason"]))
    rejected = [{"cause": r["cause"], "origin": r["origin"], "gate_run": r["id"],
                 "failed": [c["name"] + ": " + c["detail"] for c in json.loads(r["checks"]) if c["passed"] is False]}
                for r in runs if not r["passed"]]
    # a suspect rejected for having NO PATH whose component history says co-fails with a symptom: the gate is right
    # not to claim it, and the graph is probably missing an edge (Q-COUPLE-1); a human should confirm and add it
    no_path = sorted({r["cause"] for r in runs if not r["passed"]
                      and any(c["passed"] is False and c["name"].startswith("G2") for c in json.loads(r["checks"]))})
    if no_path:
        targets = {x["target"]: x["change"] for c in no_path for x in ro.run("Q-CHANGE-1", {"id": c}).rows}
        inc_row = (ro.run("Q-INC-1", {"inc": incident_id}).rows or [{}])[0]
        symptoms = set(inc_row.get("targets") or [])
        for x in ro.run("Q-COUPLE-1", {"from": sorted(targets), "min_incidents": int(weights()["knowledge"]["coupling_min"])}).rows:
            if x["cause"] in targets and x["hit"] in symptoms:
                inferred.append(Inferred(
                    claim=f"possible missing edge {x['cause']} → {x['hit']} (not a claim: no path)",
                    basis=f"{targets[x['cause']]} was rejected by G2, but {x['co_failures']} past incidents caused at "
                          f"{x['cause']} also hit {x['hit']} ({', '.join(x['incidents'][:3])}); confirm and add the edge"))
    ev = ro.run("Q-EV-1", {"ids": sorted(cited)}).rows if cited else []
    missed: dict = {}
    if chain:  # along the proof path: which hops alerted, which were silent (Culprit's "would monitors have fired?")
        inc = ro.run("Q-INC-1", {"inc": incident_id}).rows
        onset = int(inc[0]["onset_at"]) if inc and inc[0].get("onset_at") else 0
        rec = (ro.run("Q-EV-INC-TOOL", {"inc": incident_id, "tool": "alert_coverage"}).rows or [{}])[0]
        if rec.get("payload"):  # what the run recorded after its gate (same window as the evidence)
            hops = json.loads(rec["payload"])["rows"]
        else:  # an older run that did not record it: the gate's default window
            w = int(weights()["gate"]["window_min"]) * 60_000
            hops = ro.run("Q-CHAIN-MON", {"chain": chain, "since": onset - w, "until": onset + 10 * 60_000}).rows
        alerted = [h for h in hops if h["alerts"]]
        first = alerted[0] if alerted else None
        missed = {"hops": [{"hop": h["hop"], "id": h["id"], "label": h["label"], "alerted": bool(h["alerts"]),
                            "first_alert_lag_s": round((min(a["at"] for a in h["alerts"]) - onset) / 1000) if h["alerts"] else None,
                            "has_telemetry": h["has_telemetry"]} for h in hops],
                  "summary": (f"first alert at hop {first['hop'] + 1} of {len(hops)} ({first['id']}); "
                              + (f"hops before it were silent: {', '.join(h['id'] for h in hops[:first['hop']])}"
                                 if first["hop"] > 0 else "the origin itself alerted")) if first else
                             "no hop on the causal chain alerted"}
    owned: dict = {}
    cause = final["cause"] if final and final["cause"] != "NO_INCIDENT" else None
    if cause:  # who owned the changed component when the change shipped vs now (OWNED_AT history)
        ch = (ro.run("Q-CHANGE-1", {"id": cause}).rows or [{}])[0]
        if ch.get("at") is not None:
            periods = ro.run("Q-OWN-AT", {"id": ch["target"], "at": int(ch["at"])}).rows
            then = next((x["team"] for x in periods if x["covers_at"]), None)
            now = next((x["team"] for x in periods if x["current"]), None)
            owned = {"component": ch["target"], "at": int(ch["at"]), "owner_then": then, "owner_now": now,
                     "changed_hands": bool(then and now and then != now),
                     "summary": (f"{ch['target']} was owned by {then} when {cause} shipped" + (
                         f"; it has since moved to {now}, so {then} holds the context" if then and now and then != now
                         else " and still is")) if then else f"no recorded owner of {ch['target']} when {cause} shipped"}
    residue, remedy = _residue(ro, incident_id, cause if final and final["origin"] == "confirm" else None), _remedy(ro, incident_id)
    obligations = _obligations(ro, incident_id)
    return RootCauseReport(incident_id=incident_id, outcome=outcome, confident=bool(final and final["confident"]),
                           cause_id=final["cause"] if final and final["cause"] != "NO_INCIDENT" else None, mechanism=chain, proven=proven,
                           inferred=inferred, contradictions=contradictions, why_alerts_missed_it=missed, ownership=owned,
                           residue=residue, remedy=remedy, futures=_futures(ro, incident_id), obligations=obligations, rejected=rejected, evidence=ev)


# --- M12 advisory fields (re-read from the graph; neither changes a gate outcome nor the plan) ----------------------
def _residue(ro: RO, incident_id: str, cause: str | None) -> dict:
    """Residue check (Q-RESIDUE-1): how many measured-anomalous components the confirmed cause reaches."""
    if not cause:
        return {}
    rows = ro.run("Q-RESIDUE-1", {"inc": incident_id, "cause": cause}).rows
    explained = [r["id"] for r in rows if r["explained"]]
    rest = [r["id"] for r in rows if not r["explained"]]
    return {"advisory": True, "k": len(explained), "n": len(rows), "explained": explained, "unexplained": rest,
            "summary": (f"the confirmed cause explains {len(explained)} of {len(rows)} anomalous components"
                        + (f"; another fault may be active: {', '.join(rest)}" if rest else "")) if rows
            else "no anomalous measurement recorded"}


def _remedy(ro: RO, incident_id: str) -> dict:
    """Learned remediation ordering (Q-REM-1): the history line of each offered fix, or why there is none."""
    from ..actions.act import order_by_history

    plan = ro.run("Q-ACT-1", {"inc": incident_id}).rows
    if not plan:
        return {}
    syms = [r["id"] for r in ro.run("Q-INC-SYM", {"inc": incident_id}).rows]
    rows = ro.run("Q-REM-1", {"inc": incident_id, "symptoms": syms, "incidents": []}).rows
    lines = [o["history"]["line"] for o in order_by_history(plan, {"rows": rows}) if o["history"]]
    return {"applied": bool(lines), "lines": lines,
            "note": "options ordered by past outcomes on incidents sharing a symptom" if lines
            else "no usable history for the offered fixes: static order kept (no-op)"}


def _futures(ro: RO, incident_id: str) -> list[dict]:
    """Each option's predicted future as the plan recorded it (Action.future) and, after verification, whether it
    came true (the verdict's `prediction` record)."""
    out = []
    for a in ro.run("Q-ACT-1", {"inc": incident_id}).rows:
        if not a.get("future"):
            continue
        f = json.loads(a["future"])
        pr = (json.loads(a["channels"]) if a.get("channels") else {}).get("prediction") or {}
        out.append({"option": a["option"], "predicted": f["predicted"], "line": f["line"], "exposed": f.get("exposed") or [],
                    "evidence_id": f.get("evidence_id"), "verdict": a.get("verdict"), "agrees": pr.get("agrees")})
    return out


def _obligations(ro: RO, incident_id: str) -> dict:
    """Obligations at risk: the obligation clock the run recorded in ROUTE (Q-EV-INC-TOOL). If the stored payload was
    clipped, the same templates are re-run with the recorded params (telemetry after `now` is excluded by the
    template, so the numbers are the ones the run saw)."""
    from ..mcp_server.tools import breach_minutes, clock_verdict, slo_status

    rec = (ro.run("Q-EV-INC-TOOL", {"inc": incident_id, "tool": "obligation_clock"}).rows or [{}])[0]
    if not rec.get("payload"):
        return {}
    try:
        p = json.loads(rec["payload"])
        slos, customers = p["rows"], p["customers"]
    except (ValueError, KeyError):
        params = json.loads(rec["params"])
        slos = [{**x, "breach_in_min": breach_minutes(x), "status": slo_status(x)}
                for x in ro.run("Q-OBL-SLO", params["Q-OBL-SLO"]).rows]
        customers = ro.run("Q-OBL-CUST", params["Q-OBL-CUST"]).rows
    v = clock_verdict(slos, customers)
    return {"urgent": v["urgent"], "reason": v["reason"], "page_within_min": v["page_within_min"], "breach": v["breach"],
            "revenue_at_risk": v["revenue_at_risk"], "customers_reached": v["customers_reached"],
            "slos": slos, "customers": customers, "evidence_id": rec.get("evidence_id")}


def _minutes(m: float | None) -> str:
    if m is None:
        return "no breach projected"
    return f"~{m:.0f} min" if m < 120 else (f"~{m / 60:.1f} h" if m < 2880 else f"~{m / 1440:.1f} days")


def to_markdown(r: RootCauseReport) -> str:
    lines = [f"# Incident {r.incident_id}: {r.outcome}", ""]
    if r.cause_id:
        lines += [f"**Cause (gate-accepted):** `{r.cause_id}` · confident: **{r.confident}**", "",
                  "**Mechanism (G2 path):** " + " → ".join(f"`{n}`" for n in r.mechanism), ""]
    lines += ["## Proven (each claim backed by a passed gate check)", ""]
    lines += [f"- {p.claim}" + (f" [{', '.join(p.evidence_ids)}]" if p.evidence_ids else "") for p in r.proven] or ["- (none)"]
    lines += ["", "## Inferred / not established", ""]
    lines += [f"- {i.claim}: {i.basis}" for i in r.inferred] or ["- (none)"]
    if r.contradictions:
        lines += ["", "## Contradictions (active decisions the cause violates; G8 attaches, never blocks)", ""]
        lines += [f"- {c}" for c in r.contradictions]
    if r.why_alerts_missed_it:
        lines += ["", "## Why alerts missed it (alert coverage along the causal chain)", "",
                  r.why_alerts_missed_it["summary"], "", "| hop | node | alerted | first alert after onset (s) |", "|---|---|---|---|"]
        lines += [f"| {h['hop'] + 1} | `{h['id']}` | {'yes' if h['alerted'] else 'no'} | {h['first_alert_lag_s'] if h['alerted'] else '—'} |"
                  for h in r.why_alerts_missed_it["hops"]]
    if r.ownership:
        lines += ["", "## Ownership when the change shipped", "", r.ownership["summary"] + "."]
    if r.residue:
        lines += ["", "## Residue check (advisory; does not change the verdict)", "", r.residue["summary"] + "."]
    if r.remedy:
        lines += ["", "## Learned remediation ordering (reorders options only)", ""]
        lines += [f"- {x}" for x in r.remedy["lines"]] or [f"- {r.remedy['note']}"]
    if r.futures:
        lines += ["", "## Futures (each option predicted on its own GRAPH.COPY branch before approval, Q-FUTURE-1)", "",
                  "| option | predicted | why | verified | came true |", "|---|---|---|---|---|"]
        lines += [f"| {x['option']} | {x['predicted'].replace('_', ' ')} | {x['line']}"
                  + (f"; leaves {', '.join(x['exposed'])} exposed" if x["exposed"] else "")
                  + (f" [{x['evidence_id']}]" if x["evidence_id"] else "")
                  + f" | {x['verdict'] or '—'} | {'—' if x['agrees'] is None else 'yes' if x['agrees'] else 'no'} |"
                  for x in r.futures]
    if r.obligations:
        o = r.obligations
        lines += ["", "## Obligations at risk (obligation clock; decides urgency, never the cause)", "",
                  ("**URGENT: page now.** " if o["urgent"] else "Urgency unknown: " if o["urgent"] is None else "Not urgent: ")
                  + o["reason"] + "."
                  + (f" [{o['evidence_id']}]" if o.get("evidence_id") else "")]
        if o["slos"]:
            lines += ["", "| SLO | service | objective | error rate now | burn | budget left | time to breach |",
                      "|---|---|---|---|---|---|---|"]
            lines += [f"| `{x['slo']}` | `{x['service']}` | {float(x['objective']):.1%} | "
                      + (f"{float(x['error_rate']):.2%} | {float(x['burn']):.1f}x" if x.get("burn") is not None else "— | —")
                      + f" | {float(x['budget_remaining']):.0%} | {_minutes(x.get('breach_in_min'))} |" for x in o["slos"]]
        if o["customers"]:
            lines += ["", f"Customers reached through the failure: {o['customers_reached']} (each counted once), "
                          f"{o['revenue_at_risk']:,.0f} MRR at risk.", "",
                      "| customer | MRR | reached through | nearest failure path |", "|---|---|---|---|"]
            lines += [f"| `{c['customer']}` {c['name']} | {float(c['mrr']):,.0f} | "
                      + ", ".join(f"`{n}` ({v})" for n, v in zip(c["through"], c["via"]))
                      + " | " + " → ".join(f"`{n}`" for n in c["path"]) + " |" for c in o["customers"]]
    lines += ["", "## Rejected by the gate (first-class, with the failing checks)", ""]
    for rj in r.rejected:
        lines.append(f"- `{rj['cause']}` ({rj['origin']}, {rj['gate_run']}): " + "; ".join(rj["failed"]))
    lines += ["", "## Evidence", "", "| id | kind | source | about | summary |", "|---|---|---|---|---|"]
    for e in r.evidence:
        lines.append(f"| {e['id']} | {e['kind']} | {e['source']} | {', '.join(e['about'])} | {(e['summary'] or '')[:120]} |")
    return "\n".join(lines) + "\n"
