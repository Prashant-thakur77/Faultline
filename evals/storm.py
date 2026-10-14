"""S14 alert storm: grading read from the final graph state, shared by the eval harness (product check
"S14") and tests/live/test_alert_storm.py. The truth file is read here (grader), never by the product.

  run()               S14 end to end with the deterministic investigator (scenario.run_all): INTAKE groups the onset
                      alerts with algo.WCC, each incident's own gate decides its cause, a later intake round attaches the
                      late alerts. Graded: groups correct, alerts placed correctly (opened and attached), no cross-fault
                      merge, both causes confirmed, each incident's distractor rejected by the expected check.
  ungrouped_control() the same world with the pre-M14 intake: ONE incident holding every onset alert. Shows what the
                      grouping decides: how many causes the gate can confirm when the storm is not split.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # never shadow a PYTHONPATH copy (mutation check)
    sys.path.insert(0, str(ROOT / "backend"))

from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator, run_incident  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402

SID = "S14"


def truth() -> dict:
    return json.loads((ROOT / "data" / "scenarios" / f"{SID}.truth.json").read_text())


def placements(p) -> dict[str, list[dict]]:
    """alert id → the incidents it DEGRADES (how, hops, evidence), read back through the RO wrapper (Q-INC-ALERTS)."""
    ro = RO(p.tenant, p.graph)
    incs = [o.incident_id for rnd in p.intake for o in rnd.opened]
    out: dict[str, list[dict]] = {}
    for inc in incs:
        for r in ro.run("Q-INC-ALERTS", {"inc": inc}).rows:
            out.setdefault(r["alert"], []).append({"incident": inc, "how": r["how"], "hops": r["hops"],
                                                   "evidence": r["evidence"]})
    return out


def grade(p, results: list, t: dict | None = None) -> dict:
    """Grade a finished S14 run from its graph (placements) and its run results (outcomes, sweeps)."""
    t = t or truth()
    want = t["incidents"]
    onset = p.intake[0]
    opened = {o.incident_id: o for o in onset.opened}
    by_alerts = {frozenset(a["id"] for a in o.alerts): inc for inc, o in opened.items()}
    match = {i: by_alerts.get(frozenset(w["alerts"])) for i, w in enumerate(want)}  # truth incident → product incident
    placed = placements(p)
    res = {r.incident_id: r for r in results}
    rows, k, n = [], 0, 0
    for i, w in enumerate(want):
        inc = match[i]
        r = res.get(inc)
        sweep = {v["change"]: v for v in (r.sweep if r else [])}
        rejected = all(sweep.get(d, {}).get("status") == "eliminated" and sweep[d]["reason"].startswith(gate)
                       for d, gate in w.get("distractors", {}).items())
        ok_alerts = [a for a in w["alerts"] if [x["incident"] for x in placed.get(a, [])] == [inc]
                     and placed[a][0]["how"] == "opened"]
        ok_att = [a for a in w.get("attached", []) if [x["incident"] for x in placed.get(a, [])] == [inc]
                  and placed[a][0]["how"] == "attached"]
        k += len(ok_alerts) + len(ok_att)
        n += len(w["alerts"]) + len(w.get("attached", []))
        rows.append({"cause": w["cause"], "incident": inc, "outcome": r.outcome if r else None,
                     "found": bool(r) and r.outcome == w["outcome"] and r.cause_id == w["cause"] and r.confident,
                     "distractors_rejected": rejected, "chain": (r.gate or {}).get("chain") if r else None,
                     "alerts_ok": len(ok_alerts) == len(w["alerts"]), "attached_ok": len(ok_att) == len(w.get("attached", []))})
    truth_of = {a: i for i, w in enumerate(want) for a in w["alerts"] + w.get("attached", [])}
    merged = [inc for inc in {x["incident"] for xs in placed.values() for x in xs}
              if len({truth_of.get(a) for a, xs in placed.items() if any(x["incident"] == inc for x in xs)}) > 1]
    return {"incidents_expected": len(want), "incidents_opened": len(onset.opened),
            "groups_correct": len(onset.opened) == len(want) and all(match.values()),
            "alerts_placed": f"{k}/{n}", "alerts_placed_k": k, "alerts_placed_n": n, "alerts_placed_ok": k == n,
            "multi_placed": sorted(a for a, xs in placed.items() if len(xs) > 1),
            "cross_fault_merge": bool(merged),
            "causes_found": sum(1 for r in rows if r["found"]), "causes_expected": len(want),
            "all_distractors_rejected": all(r["distractors_rejected"] for r in rows),
            "attach_rounds": len(p.intake) - 1, "grouping_evidence": [rnd.evidence_id for rnd in p.intake],
            "incidents": rows}


def run(keep: bool = False) -> dict:
    t0 = time.perf_counter()
    p, results = anyio.run(lambda: scenario.run_all(SID, BaselineInvestigator(), keep=True, set_mode=False))
    try:
        out = grade(p, results)
        out["errors"] = [r.error for r in results if r.error]
    finally:
        if not keep:
            gcopy.delete_if_exists(gclient.engine(), p.graph)
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out | ({"graph": p.graph} if keep else {})


def ungrouped_control() -> dict:
    """The same world, but every onset alert in ONE incident (what INTAKE did before M14). The product's own incidents
    from the grouped intake also exist in the graph but are never investigated here."""
    p = scenario.prepare(SID, tag=uuid.uuid4().hex[:8], set_mode=False)
    try:
        alerts = sorted((a for o in p.groups for a in o.alerts), key=lambda a: (int(a["fired_at"]), a["id"]))
        targets = sorted({a["target"] for a in alerts})
        inc, run_id = f"{p.incident_id}-ungrouped", f"{p.run_id}-ungrouped"
        g = gclient.engine().select_graph(p.graph)
        writes.open_incident(g, inc=inc, run=run_id, tenant=p.tenant, title=p.scenario["name"], report=p.scenario["report"],
                             onset=p.onset_ms, symptoms=[{"id": f"sym-{k}-{x}", "kind": k, "target": x} for x in targets
                                                         for k in [next(a["metric"] for a in alerts if a["target"] == x)]],
                             models="", mode="scenario")
        scenario.embed_incident(g, inc, p.scenario["report"], scenario.symptom_texts(alerts, targets))
        writes.advance_stage(g, inc=inc, run=run_id, stage="INTAKE", ord_=1, note="eval control: all alerts, ungrouped")
        r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=inc, onset_ms=p.onset_ms, symptoms=targets,
                                           investigator=BaselineInvestigator(), graph=p.graph, run_id=run_id,
                                           window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    want = truth()["incidents"]
    cause_of = {a: w["cause"] for w in want for a in w["alerts"]}
    claimed = r.cause_id if r.outcome in ("CONFIRMED", "NOT_CONFIDENT") else None
    swept = {v["change"]: v["status"] for v in r.sweep}
    # one incident can name at most one cause: every alert whose true cause is another change is explained wrongly
    wrong = sorted(a["id"] for a in alerts if claimed and cause_of.get(a["id"]) != claimed)
    return {"symptoms": targets, "outcome": r.outcome, "cause": r.cause_id, "confident": r.confident,
            "causes_found": int(r.outcome == "CONFIRMED" and claimed in {w["cause"] for w in want}),
            "causes_expected": len(want), "alerts_misattributed": len(wrong), "alerts_total": len(alerts),
            "true_cause_eliminated": sorted(w["cause"] for w in want if swept.get(w["cause"]) == "eliminated"),
            "confident_misattribution": bool(wrong) and r.confident,
            "sweep": [{"change": v["change"], "status": v["status"], "reason": v["reason"]} for v in r.sweep],
            "error": r.error}


if __name__ == "__main__":
    print(json.dumps({"S14": run(), "S14_ungrouped": ungrouped_control()}, indent=2, default=str))
