"""Live: the HTTP contract end to end on the hero scenario (keyless). run → AWAITING_APPROVAL → plan (with
memory) → choose → stale hash 409 → approve → background EXECUTE/VERIFY/WRITEBACK → RESOLVED."""

import time

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy

pytestmark = pytest.mark.live


def _wait(client, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(f"{inc} did not reach {stages} (last {st})")


def test_hero_over_http():
    api._rate.clear()
    with TestClient(api.app) as client:
        assert client.get("/api/status").json()["status"] == "ok"
        r = client.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
        inc, graph = r["incident"], r["graph"]
        try:
            assert _wait(client, inc, {"AWAITING_APPROVAL", "FAILED", "UNKNOWN_ESCALATED"}) == "AWAITING_APPROVAL"
            view = client.get(f"/api/incidents/{inc}").json()
            assert [s["stage"] for s in view["stages"]][:3] == ["INTAKE", "RECALL", "LOCALIZE"]
            plan = client.get(f"/api/incidents/{inc}/plan").json()
            assert plan["containment_cut"] and plan["who_fixes"]
            assert plan["memory"]["recalled"] and plan["memory"]["fix_history"]
            opt = next(o for o in plan["options"] if o["kind"] == "flip_flag" and o["enabled"])
            spec = client.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
            bad = client.post(f"/api/incidents/{inc}/approve",
                              json={"action_id": opt["id"], "plan_hash": "0" * 64, "approver": "p-030"})
            assert bad.status_code == 409
            ok = client.post(f"/api/incidents/{inc}/approve",
                             json={"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"})
            assert ok.status_code == 200 and ok.json()["approved"]
            assert _wait(client, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED"}) == "RESOLVED"
            stages = client.get(f"/api/incidents/{inc}").json()["stages"]
            assert "write-back verified 7/7" in next(s["note"] for s in stages if s["stage"] == "RESOLVED")
            assert client.post(f"/api/incidents/{inc}/approve",  # approving again after resolution is refused
                               json={"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"}).status_code == 409
        finally:
            gcopy.delete_if_exists(gclient.engine(), graph)


def test_unknown_incident_is_404():
    with TestClient(api.app) as client:
        assert client.get("/api/incidents/inc-does-not-exist").status_code == 404


def test_scenario_run_with_the_graph_off_is_503_like_every_route(monkeypatch):
    """A4 over HTTP: starting a scenario with FalkorDB disabled fails loudly with 503, not a generic 500 (prejudge)."""
    from faultline.config import settings

    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    with TestClient(api.app) as client:
        r = client.post("/api/scenarios/S1/run", json={})
        assert r.status_code == 503, r.text
        assert client.get("/api/graph").status_code == 503


def test_preflight_by_repo_and_number_fetches_the_pr_itself(monkeypatch):
    """§6.14: a preflight can name the PR ({repo, number}); the server reads its files from GitHub (here the simulated
    world of the tenant graph) and decides from the graph. Public mode: assessed on a clean room, never recorded."""
    import json as _json

    from faultline.actions import github as gh
    from faultline.config import settings

    monkeypatch.setattr(settings, "faultline_public", True)
    hub = gh.client("tenant_acme")
    repo = "eval/preflight-fetch"
    hub.seed(repo, "src/payment/config.json", _json.dumps({"client": {"timeout_ms": 1500, "retries": 2}}, indent=2))
    hub.create_branch(repo, "faultline/fix-test-risky")
    hub.put_file(repo, "faultline/fix-test-risky", "src/payment/config.json",
                 _json.dumps({"client": {"timeout_ms": 5000, "retries": 0}}, indent=2), "raise timeout, drop retries")
    pr = hub.open_pr(repo, "faultline/fix-test-risky", "payment: raise timeout, drop retries", "test")
    g = gclient.engine().select_graph("tenant_acme")
    monkeypatch.setattr(settings, "faultline_preflight_key", "test-preflight-key")
    try:
        with TestClient(api.app) as client:
            # an anonymous visitor cannot make the server read a repo the tenant graph does not know (operator's gh auth)
            r = client.post("/api/preflight", json={"repo": repo, "number": pr["number"]})
            assert r.status_code == 403 and "not a repository" in r.text
            # the preflight key lifts the allowlist (the PR fetch is attempted: no such PR → 502)
            assert client.post("/api/preflight", json={"repo": repo, "number": 999},
                               headers={"Authorization": "Bearer test-preflight-key"}).status_code == 502
            g.query("CREATE (:PR:Node {id: 'pr:test-known-repo', repo: $r})", {"r": repo})   # now the graph knows it
            r = client.post("/api/preflight", json={"repo": repo, "number": pr["number"]})
            assert r.status_code == 200, r.text
            out = r.json()
            assert out["verdict"] == "block" and out["recorded"] is False
            assert {d["id"] for d in out["decision_links"]} >= {"ADR-012", "ADR-013"}
            assert client.post("/api/preflight", json={"repo": repo, "number": 999}).status_code == 502   # no such PR
            assert client.post("/api/preflight", json={"repo": "bad repo", "number": 1}).status_code == 422
    finally:
        g.query("MATCH (p:PR {id: 'pr:test-known-repo'}) DELETE p")
        gh.reset_sim("tenant_acme")


def test_hourly_llm_budget_turns_the_demo_replay_only(monkeypatch):
    """§11.3: live-LLM spend is costed per run on the audit graph; past the hourly budget, LLM runs are refused (429)
    and /api/status says replay-only, while the deterministic investigator still runs."""
    import uuid as _uuid

    from faultline.config import settings
    from faultline.graph import client as gc
    from faultline.graph import writes
    from faultline.graph.tenant import audit_graph

    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-used")   # never called: the budget refuses first
    audit = gc.engine().select_graph(audit_graph(settings.faultline_tenant))   # the one global ledger
    run = f"run-budget-{_uuid.uuid4().hex[:8]}"
    assert writes.reserve_llm(audit, id=f"llm-run-{run}", run=run, tenant="acme", kind="run", est_usd=0.0,
                              limit_usd=1e9, since=0)
    writes.settle_llm(audit, id=f"llm-run-{run}", tin=100_000, tout=10_000, usd=999.0)
    try:
        with TestClient(api.app) as client:
            assert client.get("/api/status").json()["llm_budget"]["replay_only"] is True
            r = client.post("/api/scenarios/S1/run", json={"llm": "anthropic"})
            assert r.status_code == 429 and "budget" in r.text
    finally:
        audit.query("MATCH (x:LlmSpend {id:$r}) DELETE x", {"r": f"llm-run-{run}"})
    with TestClient(api.app) as client:
        assert client.get("/api/status").json()["llm_budget"]["replay_only"] is False
