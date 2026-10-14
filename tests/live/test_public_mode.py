"""Live: the public-demo envelope (FAULTLINE_PUBLIC=true). Visitors cannot act on someone else's run, cannot
mutate the live tenant graph through forget or preflight, cannot spend on the LLM, and bad input is a 4xx."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy

pytestmark = pytest.mark.live


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(settings, "faultline_public", True)
    api._rate.clear()
    with TestClient(api.app) as c:
        yield c


def _wait(c, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(st)


def test_only_the_run_token_holder_can_choose_and_approve(public):
    c = public
    r = c.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
    inc, token, graph = r["incident"], r["run_token"], r["graph"]
    try:
        assert _wait(c, inc, {"AWAITING_APPROVAL"}) == "AWAITING_APPROVAL"
        opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["enabled"])
        assert c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).status_code == 403
        assert c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]},
                      headers={"X-Faultline-Run-Token": "nope"}).status_code == 403
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]},
                      headers={"X-Faultline-Run-Token": token}).json()
        # reject is guarded exactly like approve: without the run token it is refused and nothing is recorded
        assert c.post(f"/api/incidents/{inc}/reject", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                            "approver": "p-030", "reason": "not my run"}).status_code == 403
        bad = c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                           "approver": "not-a-person"}, headers={"X-Faultline-Run-Token": token})
        assert bad.status_code == 422  # the graph decides who may approve
        ok = c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                          "approver": "p-030"}, headers={"X-Faultline-Run-Token": token})
        assert ok.status_code == 200 and ok.json()["approver"]["id"] == "p-030"
        assert _wait(c, inc, {"RESOLVED", "UNKNOWN_ESCALATED", "FAILED"}) == "RESOLVED"
    finally:
        gcopy.delete_if_exists(gclient.engine(), graph)


def test_forget_runs_in_a_clean_room_and_the_tenant_graph_is_untouched(public):
    c = public
    d = c.post("/api/memory/forget", json={"doc_id": "doc-adr-004"}).json()
    r = c.post("/api/memory/forget", json={"doc_id": "doc-adr-004", "token": d["token"], "approver": "p-030"}).json()
    assert r["clean_room"] is True and r["graph"].startswith("eval_acme_forget_") and r["nodes"] == 2
    still = gclient.engine().select_graph("tenant_acme").ro_query("MATCH (d:Decision {id:'ADR-004'}) RETURN count(d)").result_set[0][0]
    assert still == 1
    assert not gcopy.exists(gclient.engine(), r["graph"])  # the clean room is removed afterwards


def test_unkeyed_preflight_is_assessed_but_not_recorded(public):
    c = public
    before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}}, indent=2)
    bad = json.dumps({"client": {"timeout_ms": 9000, "retries": 2}}, indent=2)
    body = {"repo": "visitor/app", "number": 9911, "title": "t", "author": "x",
            "files": [{"path": "src/payment/config.json", "before": before, "after": bad}]}
    r = c.post("/api/preflight", json=body).json()
    assert r["verdict"] == "block" and r["recorded"] is False
    assert c.get("/api/preflight", params={"pr": "pr:visitor/app#9911"}).status_code == 404


def test_no_anonymous_llm_spend_and_bad_input_is_422(public, monkeypatch):
    c = public
    monkeypatch.setattr(settings, "anthropic_api_key", "configured-but-not-for-visitors")
    assert c.post("/api/brain/ask", json={"question": "who knows payment?", "llm": "anthropic"}).status_code == 403
    assert c.post("/api/scenarios/S1/run", json={"llm": "anthropic"}).status_code == 403
    assert c.get("/api/incidents", params={"tenant": "ACME!"}).status_code == 422


def test_the_run_token_is_returned_and_works_when_prepare_outlasts_the_wait(public, monkeypatch):
    """The endpoint waits up to 5 s for the incident. A slower prepare must not cost the visitor the token: it is made
    before the job starts, returned anyway, and the job writes its hash on the run once INTAKE opens it."""
    from faultline import scenario

    real = scenario.prepare

    def slow(*a, **k):
        time.sleep(5.5)
        return real(*a, **k)

    monkeypatch.setattr(scenario, "prepare", slow)
    c = public
    r = c.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
    assert r["run_token"] and "incident" not in r, r
    inc = f"inc-s1-{r['job']}"
    t0 = time.time()
    while time.time() - t0 < 60 and not any(x.get("incident") == inc for x in c.get("/api/incidents").json()):
        time.sleep(0.3)
    graph = next(x["graph"] for x in c.get("/api/incidents").json() if x.get("incident") == inc)
    try:
        assert _wait(c, inc, {"AWAITING_APPROVAL"}) == "AWAITING_APPROVAL"
        opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["enabled"])
        assert c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).status_code == 403
        ok = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]},
                    headers={"X-Faultline-Run-Token": r["run_token"]})
        assert ok.status_code == 200, ok.text
    finally:
        gcopy.delete_if_exists(gclient.engine(), graph)
