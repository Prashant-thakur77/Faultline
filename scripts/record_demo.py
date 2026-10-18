"""Record demo runs THROUGH THE API (keyless, simulated GitHub) and export everything the incident room reads, for
the static replay: examples/<name>/{incident,plan,blast,graph}.json + the graph exports (events, gate runs, tool
calls, hypotheses, report) + the run artefacts (transcript.jsonl, verify.txt, pr.md, cost.json; scripts/
run_artefacts.py). The graph is the record; these are exports of it.

    PYTHONPATH=backend uv run python scripts/record_demo.py                 # s1-hero (approved → RESOLVED), s2-data-incident
    PYTHONPATH=backend uv run python scripts/record_demo.py s4 s5 s6        # S4S control, S5 bad fixes, S6 preflight block
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from faultline import api  # noqa: E402
from faultline.actions import github as gh  # noqa: E402

from export_run import export  # noqa: E402
from run_artefacts import write as write_artefacts  # noqa: E402

TERMINAL = {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "NO_INCIDENT"}


def _wait(c, inc, stages, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise RuntimeError(f"{inc}: did not reach {stages}")


def record(c: TestClient, sid: str, name: str, approve_kind: str | None) -> dict:
    r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"}).json()
    inc, graph = r["incident"], r["graph"]
    st = _wait(c, inc, TERMINAL | {"AWAITING_APPROVAL"})
    if st == "AWAITING_APPROVAL" and approve_kind:
        plan = c.get(f"/api/incidents/{inc}/plan").json()
        opt = next(o for o in plan["options"] if o["kind"] == approve_kind and o["enabled"])
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
        top = (plan.get("who_fixes") or {}).get("payload", {}).get("rows", [{}])[0].get("person", "p-030")
        c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": top})
        _wait(c, inc, TERMINAL | {"AWAITING_APPROVAL"} - {"AWAITING_APPROVAL"})
    out = ROOT / "examples" / name
    view = c.get(f"/api/incidents/{inc}").json()
    run = view["run"]["run"]
    stats = export("acme", graph, inc, run, out, view["run"].get("outcome") or "")
    for fname, path in (("incident.json", f"/api/incidents/{inc}"), ("plan.json", f"/api/incidents/{inc}/plan"),
                        ("blast.json", f"/api/incidents/{inc}/blast"), ("graph.json", f"/api/graph?incident={inc}")):
        res = c.get(path)
        if res.status_code == 200:
            (out / fname).write_text(json.dumps(res.json(), indent=2, default=str))
    (out / "manifest.json").write_text(json.dumps({"scenario": sid, "incident": inc, "run": run, "graph": graph,
                                                   "final_stage": view["incident"]["stage"], "github": "simulated",
                                                   "investigator": view["run"]["investigator"], **stats}, indent=2))
    write_artefacts(out)
    return {"name": name, "incident": inc, "stage": view["incident"]["stage"], **stats}


def _start(c: TestClient, sid: str) -> tuple[str, str, str]:
    r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"}).json()
    inc, graph = r["incident"], r["graph"]
    _wait(c, inc, TERMINAL | {"AWAITING_APPROVAL"})
    return inc, graph, c.get(f"/api/incidents/{inc}").json()["run"]["run"]


def _approve(c: TestClient, inc: str, aid: str) -> str:
    """Choose → approve the exact action by its plan hash, through the API; wait for the action job to finish."""
    spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": aid}).json()
    plan = c.get(f"/api/incidents/{inc}/plan").json()
    top = (plan.get("who_fixes") or {}).get("payload", {}).get("rows", [{}])[0].get("person", "p-030")
    r = c.post(f"/api/incidents/{inc}/approve", json={"action_id": aid, "plan_hash": spec["plan_hash"], "approver": top})
    if r.status_code != 200:
        raise RuntimeError(f"approve {aid}: HTTP {r.status_code} {r.text[:200]}")
    t0 = time.time()
    while time.time() - t0 < 300:  # the approval moved the incident to EXECUTE; wait until the job leaves it
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st not in ("EXECUTE", "VERIFY", "WRITEBACK", "LEARN"):
            return st
        time.sleep(0.3)
    raise RuntimeError(f"{inc}: action job did not finish")


def _rejected(c: TestClient, inc: str, aid: str, out: Path) -> dict:
    act_row = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["id"] == aid)
    from run_artefacts import _events, _writeback

    return {"incident": inc, "action": aid, "kind": act_row["kind"], "option": act_row["option"], "target": act_row["target"],
            "verdict": act_row["verdict"], "explanation": act_row["explanation"], "channels": act_row["channels"],
            "external_ref": act_row["external_ref"], "stage_after": c.get(f"/api/incidents/{inc}").json()["incident"]["stage"],
            "success_written": _writeback(_events(out)) is not None if out.exists() else None}


def record_s5(c: TestClient) -> dict:
    """S5: bad fixes are rejected by verification, never written as success.
    Service: force the plan "roll back the same-minute distractor" on the S1 incident (an option the agent did not
    offer), approve it through the API → the second channel says NOT_APPLIED (checkout errors unchanged).
    Data: on the S2 incident, propose a blanket patch that drops every cloudpay_v2 order (hides the KPI jump by
    deleting revenue), approve it → the rebuild + invariant suite catches it, the patch is reverted."""
    from faultline import repair, scenario
    from faultline.actions import act
    from faultline.actions import github as gh
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph import writes

    out = ROOT / "examples" / "s5-bad-fix"
    inc, graph, run = _start(c, "S1")
    ctx = act.Ctx("acme", graph, inc, run)
    aid = f"act-{inc}-bad"
    writes.record_option(ctx.g(), inc=inc, aid=aid, kind="rollback_deploy", option="roll back D-email-88 (forced bad plan)",
                         enabled=True, reason="S5: forced bad plan, roll back the same-minute distractor instead of the cause",
                         target="D-email-88", preview={"repo": act.INFRA_REPO, "path": act.DEPLOYS_PATH, "service": "email",
                                                       "revert": "D-email-88"})
    _approve(c, inc, aid)
    stats = export("acme", graph, inc, run, out, "")
    for fname, path in (("incident.json", f"/api/incidents/{inc}"), ("plan.json", f"/api/incidents/{inc}/plan")):
        (out / fname).write_text(json.dumps(c.get(path).json(), indent=2, default=str))
    view = c.get(f"/api/incidents/{inc}").json()
    (out / "manifest.json").write_text(json.dumps({"scenario": "S5", "base_scenario": "S1", "incident": inc, "run": run,
                                                   "graph": graph, "final_stage": view["incident"]["stage"],
                                                   "github": "simulated", "investigator": view["run"]["investigator"],
                                                   "variants": {"service": "remediation_rejected.json",
                                                                "data": "data_bad_fix_rejected.json"}, **stats}, indent=2))
    svc = _rejected(c, inc, aid, out)
    gh.reset_sim(graph)  # the forced rollback lives only in this clean room's simulated world: discard both
    gcopy.delete_if_exists(gclient.engine(), graph)
    svc.update(variant="service", scenario="S1", environment_restored=not gcopy.exists(gclient.engine(), graph),
               restored_how="the clean room (eval graph) and its simulated GitHub world were discarded after export")
    (out / "remediation_rejected.json").write_text(json.dumps(svc, indent=2, default=str) + "\n")
    # data variant
    target = "pipeline/transforms/stg_orders.sql"
    original = (ROOT / target).read_text()
    inc2, graph2, run2 = _start(c, "S2")
    ctx2 = act.Ctx("acme", graph2, inc2, run2)
    bad = original.replace("WHERE status NOT IN ('cancelled', 'refunded');",
                           "WHERE status NOT IN ('cancelled', 'refunded')\n  AND payment_processor <> 'cloudpay_v2';")
    if bad == original:
        raise RuntimeError(f"{target} changed shape; update the blanket bad patch")
    rp = act.propose_data_repair(ctx2, file=target, new_content=bad,
                                 reasoning="blanket filter: drop every cloudpay_v2 order so the KPI jump disappears")
    try:
        stage2 = _approve(c, inc2, rp["id"])
        row = _rejected(c, inc2, rp["id"], Path("/nonexistent"))
    finally:
        restored_file = (ROOT / target).read_text() == original
        if not restored_file:  # fail loudly but put the transform back first
            (ROOT / target).write_text(original)
        repair.cleanup_backups()
        scenario.set_pipeline_mode("incident")  # rebuild the warehouse from the original transforms
    gcopy.delete_if_exists(gclient.engine(), graph2)
    row.update(variant="data", scenario="S2", file=target, diff=rp["diff"], reasoning=rp["reasoning"], stage_after=stage2,
               success_written=row["verdict"] == "APPLIED", environment_restored=restored_file
               and not list((ROOT / "pipeline" / "transforms").glob("*.sql.orig")),
               restored_how="the verifier reverted the patch (NOT_APPLIED); the warehouse was rebuilt from the original "
                            "transforms (incident fixture)")
    (out / "data_bad_fix_rejected.json").write_text(json.dumps(row, indent=2, default=str) + "\n")
    write_artefacts(out)
    return {"name": "s5-bad-fix", "service": svc["verdict"], "data": row["verdict"]}


def record_s6() -> dict:
    """S6 Mode B: the preflight of a PR that raises the payment client timeout to 5000 ms and drops
    retries, on a fresh clean room of golden_acme; exported from the graph (the preflight Run, its tool calls and the
    preflight_change evidence). Mode A (G8 attaches ADR-012 to the S1 cause) is in examples/s1-hero/gate_runs.json."""
    import uuid

    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO
    from faultline.preflight.engine import PreflightIn, run

    out = ROOT / "examples" / "s6-preflight-block"
    out.mkdir(parents=True, exist_ok=True)
    before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}}, indent=2)
    after = json.dumps({"client": {"timeout_ms": 5000, "retries": 0}}, indent=2)
    room = f"eval_acme_preflight_{uuid.uuid4().hex[:8]}"
    db = gclient.engine()
    gcopy.copy_graph(db, "golden_acme", room)
    try:
        pin = PreflightIn(repo="Prashant-thakur77/faultline-demo-app", number=9900,
                          title="payment: raise client timeout to 5000 ms, drop retries", author="eval",
                          files=[{"path": "src/payment/config.json", "before": before, "after": after}])
        r = run("acme", pin, graph=room)
        ro = RO("acme", room)
        rec = ro.run("Q-PRE-LAST", {"pr": r["pr"]}).rows[0]
        calls = ro.run("Q-RUN-2", {"run": r["run_id"]}).rows
    finally:
        gcopy.delete_if_exists(db, room)
    (out / "preflight.json").write_text(json.dumps({"input": pin.model_dump(), "result": r,
                                                    "recorded": {**rec, "payload": json.loads(rec["payload"])}},
                                                   indent=2, default=str) + "\n")
    (out / "tool_calls.json").write_text(json.dumps(calls, indent=2, default=str))
    (out / "events.jsonl").write_text("".join(json.dumps({"type": "tool_call", **x}, default=str) + "\n" for x in calls))
    rows = [f"| {d['id']} | {d.get('title', '')} |" for d in r["decision_links"]]
    (out / "report.md").write_text("\n".join([
        f"# Preflight {r['pr']}: **{r['verdict']}** (risk {r['risk']})", "",
        "S6 Mode B. Exported from the graph (the preflight Run's `preflight_change` evidence); clean room of golden_acme.", "",
        "## Decisions this change contradicts", "", "| decision | title |", "|---|---|", *rows, "",
        "## Required reviewers", "", *[f"- {x}" if not isinstance(x, dict) else
                                       f"- {x.get('person') or x.get('id')}" + (f" ({x['why']})" if x.get("why") else "")
                                       for x in r["reviewers"]], "",
        "## Would change if", "", *[f"- {w}" for w in r["would_change_if"]], "",
        f"Evidence `{r['evidence']['evidence_id']}` · template `{r['evidence']['template']}` · {r['evidence']['served_by']}", "",
        "Mode A (the same contradiction found during an incident): G8 attaches ADR-012 to the S1 cause, see "
        "`examples/s1-hero/gate_runs.json` (check `G8 contradiction`).", ""]))
    (out / "manifest.json").write_text(json.dumps({"kind": "preflight", "scenario": "S6", "pr": r["pr"], "run": r["run_id"],
                                                   "graph": room, "verdict": r["verdict"], "risk": r["risk"],
                                                   "decisions": sorted(d["id"] for d in r["decision_links"]),
                                                   "investigator": "preflight (deterministic scoring, weights.yaml)",
                                                   "final_stage": f"PREFLIGHT_{r['verdict'].upper()}", "tool_calls": len(calls),
                                                   "wall_s": round(r["ms"] / 1000, 3)}, indent=2))
    write_artefacts(out)
    return {"name": "s6-preflight-block", "verdict": r["verdict"], "risk": r["risk"]}


def main() -> int:
    which = set(sys.argv[1:]) or {"s1", "s2"}
    gh.reset_sim()
    api._rate.clear()
    with TestClient(api.app) as c:
        if "s1" in which:
            print(record(c, "S1", "s1-hero", "flip_flag"))
        # each recording starts from a fresh simulated GitHub: S1's approved flag must not leak into S2's plan as
        # "already off at main (drift)"
        if "s2" in which:
            gh.reset_sim()
            try:
                print(record(c, "S2", "s2-data-incident", "data_repair"))
            finally:  # the approved repair stays applied on disk, as it would in production: put the fixture back
                from faultline import repair, scenario

                repair.restore_pristine()
                scenario.set_pipeline_mode("incident")
        if "s4" in which:
            gh.reset_sim()
            print(record(c, "S4S", "s4-no-incident", None))
        if "s5" in which:
            gh.reset_sim()
            print(record_s5(c))
    if "s6" in which:
        print(record_s6())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
