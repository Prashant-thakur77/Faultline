"""Live: a scenario whose alerts INTAKE splits into several incidents (S14: alert storm + an unrelated concurrent fault)
started over HTTP. The API investigates EVERY incident (one job, in sequence), indexes each with its own run, lists
them all, serves each one's view, plan and event stream, and accepts the job's run token on each. Approving the storm's
real fix while the other incident is still open verifies APPLIED through the background job, with the other incident's
share of the symptoms allowed and shown (Q-VERIFY-ALLOW)."""

import json
import sys
import time
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))  # evals only: never the repo's backend/
import storm  # noqa: E402

from faultline import api  # noqa: E402
from faultline.config import settings  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402

pytestmark = pytest.mark.live


def _wait(c, inc, stages, timeout=180):
    t0, st = time.time(), None
    while time.time() - t0 < timeout:
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(f"{inc} did not reach {stages} (last {st})")


def _first_sse_stage(inc: str) -> dict | None:
    """The incident's event stream (the route's own generator, read directly: TestClient buffers SSE) up to its first
    `stage` event, bounded by a timeout so a silent stream fails instead of hanging."""

    class _Req:  # the two things the route reads from the request
        client = None

        async def is_disconnected(self) -> bool:
            return False

    async def first():
        resp = await api.incident_events(inc, _Req(), tenant="acme")
        it = resp.body_iterator
        try:
            with anyio.fail_after(20):
                async for item in it:
                    if item.get("event") == "stage":
                        return json.loads(item["data"])
        finally:
            await it.aclose()
        return None

    return anyio.run(first)


@pytest.fixture(scope="module")
def storm_run():
    """S14 over HTTP in public mode (so the run token matters), deleted afterwards."""
    old = settings.faultline_public
    settings.faultline_public = True
    api._rate.clear()
    try:
        with TestClient(api.app) as c:
            r = c.post("/api/scenarios/S14/run", json={"llm": "baseline"})
            assert r.status_code == 200, r.text
            body = r.json()
            try:
                incs = [x["incident"] for x in body["incidents"]]
                for inc in incs:
                    assert _wait(c, inc, {"AWAITING_APPROVAL", "FAILED", "UNKNOWN_ESCALATED", "NO_INCIDENT"}) == \
                        "AWAITING_APPROVAL"
                yield c, body
            finally:
                gcopy.delete_if_exists(gclient.engine(), body["graph"])
    finally:
        settings.faultline_public = old


def test_the_run_reports_every_incident_intake_opened(storm_run):
    c, body = storm_run
    xs = body["incidents"]
    assert len(xs) == 2 and len({x["run"] for x in xs}) == 2 and len({x["incident"] for x in xs}) == 2
    assert body["incident"] == xs[0]["incident"] and body["run"] == xs[0]["run"]  # unchanged headline fields
    assert all(x["intake_round"] == 1 and x["symptoms"] for x in xs)
    assert not set(xs[0]["symptoms"]) & set(xs[1]["symptoms"])
    assert body["run_token"]


def test_incident_listing_shows_each_incident_with_its_own_run_and_cause(storm_run):
    c, body = storm_run
    rows = {r["incident"]: r for r in c.get("/api/incidents").json()}
    mine = [rows[x["incident"]] for x in body["incidents"]]
    assert [r["run"] for r in mine] == [x["run"] for x in body["incidents"]]
    assert {r["graph"] for r in mine} == {body["graph"]} and {r["scenario"] for r in mine} == {"S14"}
    assert all(r["outcome"] == "CONFIRMED" for r in mine)
    assert sorted(r["cause"] for r in mine) == sorted(w["cause"] for w in storm.truth()["incidents"])


def test_each_incident_has_its_own_view_plan_and_event_stream(storm_run):
    c, body = storm_run
    for x in body["incidents"]:
        view = c.get(f"/api/incidents/{x['incident']}").json()
        assert view["run"]["run"] == x["run"] and view["stages"][0]["stage"] == "INTAKE"
        assert sorted(view["incident"]["targets"]) == sorted(x["symptoms"])
        plan = c.get(f"/api/incidents/{x['incident']}/plan").json()
        assert plan["stage"] == "AWAITING_APPROVAL" and any(o["enabled"] for o in plan["options"])
    ev = _first_sse_stage(body["incidents"][1]["incident"])
    assert ev and ev["stage"] == "INTAKE", ev


def test_the_jobs_run_token_is_accepted_on_every_incident(storm_run):
    c, body = storm_run
    inc = body["incidents"][1]["incident"]
    opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["enabled"])
    assert c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).status_code == 403
    ok = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]},
                headers={"X-Faultline-Run-Token": body["run_token"]})
    assert ok.status_code == 200 and ok.json()["plan_hash"]


def test_approving_the_storm_fix_verifies_applied_with_the_open_incidents_share_allowed(storm_run):
    c, body = storm_run
    pay_cause = storm.truth()["incidents"][0]["cause"]
    rows = {r["incident"]: r for r in c.get("/api/incidents").json()}
    inc = next(x["incident"] for x in body["incidents"] if rows[x["incident"]]["cause"] == pay_cause)
    other = next(x["incident"] for x in body["incidents"] if x["incident"] != inc)
    hdr = {"X-Faultline-Run-Token": body["run_token"]}
    opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"]
               if o["enabled"] and o["kind"] == "flip_flag")
    spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}, headers=hdr).json()
    ok = c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                      "approver": "p-030"}, headers=hdr)
    assert ok.status_code == 200, ok.text
    assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED"}) == "RESOLVED"
    act_row = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["id"] == opt["id"])
    assert act_row["verdict"] == "APPLIED" and other in act_row["explanation"]
    tel = act_row["channels"]["telemetry"]
    assert tel["allowance"]["template"] == "Q-VERIFY-ALLOW"
    assert {r["incident"] for r in tel["allowance"]["rows"]} == {other}
    # the other incident is untouched and still waiting for its own approval
    assert c.get(f"/api/incidents/{other}").json()["incident"]["stage"] == "AWAITING_APPROVAL"
