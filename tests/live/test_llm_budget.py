"""Live: the live-LLM budget is ONE global ledger (not per tenant). Each run or brain question reserves an estimate
first, in one atomic query, so concurrent requests cannot all pass the same remaining budget; afterwards the
reservation is settled with the real usage, also for a failed run (its partial usage)."""

import threading
import types
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.config import settings
from faultline.graph import client as gc
from faultline.graph import writes
from faultline.graph.tenant import audit_graph

pytestmark = pytest.mark.live


@pytest.fixture
def ledger(monkeypatch):
    """A budget with exactly `room` dollars left above what the ledger already holds this hour; rows cleaned after."""
    g = gc.engine().select_graph(audit_graph(settings.faultline_tenant))
    tag = uuid.uuid4().hex[:6]
    used = api._llm_spend()["usd_last_hour"]

    def room(usd: float) -> None:
        monkeypatch.setattr(settings, "faultline_llm_budget_usd_per_hour", round(used + usd, 6))

    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-used")
    yield types.SimpleNamespace(g=g, tag=tag, room=room)
    g.query("MATCH (x:LlmSpend) WHERE x.run STARTS WITH $t OR x.tenant = $t DELETE x", {"t": f"t{tag}"})


def _rows(g, run_prefix: str) -> list[dict]:
    res = g.query("MATCH (x:LlmSpend) WHERE x.run STARTS WITH $p RETURN x.id, x.state, x.usd, x.reserved_usd, x.tenant "
                  "ORDER BY x.id", {"p": run_prefix}).result_set
    return [dict(zip(("id", "state", "usd", "reserved_usd", "tenant"), r)) for r in res]


def test_concurrent_reservations_cannot_all_pass(ledger):
    ledger.room(1.0)                                   # room for exactly two 0.5 reservations
    wins, barrier = [], threading.Barrier(8)

    def go(i):
        barrier.wait()
        if writes.reserve_llm(ledger.g, id=f"llm-run-t{ledger.tag}-{i}", run=f"t{ledger.tag}-{i}", tenant="acme",
                              kind="run", est_usd=0.5, limit_usd=settings.faultline_llm_budget_usd_per_hour,
                              since=0):
            wins.append(i)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(wins) == 2 and len(_rows(ledger.g, f"t{ledger.tag}")) == 2


def test_the_budget_is_global_across_tenants(ledger):
    ledger.room(0.7)
    lid = api._reserve_llm("run", f"t{ledger.tag}-gx", "globex")  # a globex run spends the same hour's budget
    with TestClient(api.app) as c:
        b = c.get("/api/status?tenant=acme").json()["llm_budget"]
        assert b["scope"] == "global" and b["reserved_usd"] >= 0.5 and b["replay_only"] is True
        r = c.post("/api/scenarios/S1/run", json={"llm": "anthropic"})       # an acme run no longer fits
        assert r.status_code == 429 and "budget" in r.text
    api._settle_llm(lid, {"input_tokens": 1000, "output_tokens": 100}, "settled")
    row = _rows(ledger.g, f"t{ledger.tag}-gx")[0]
    assert row["state"] == "settled" and row["tenant"] == "globex" and 0 < row["usd"] < 0.5


def test_a_failed_run_records_its_partial_usage(ledger, monkeypatch):
    from faultline import scenario
    from faultline.agent import loop

    class Inv:
        name = "fake-llm"

        def __init__(self):
            self.usage = {"input_tokens": 20_000, "output_tokens": 2_000}   # spent before the failure

    monkeypatch.setattr(loop, "LLMInvestigator", Inv)
    monkeypatch.setattr(scenario, "prepare", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom mid-run")))
    ledger.room(5.0)
    job = f"t{ledger.tag}-fail"
    lid = api._reserve_llm("run", job, "acme")
    api._jobs[job] = {"state": "running"}
    api._run_job(job, "S1", "anthropic", lid)
    assert api._jobs.pop(job)["state"] == "failed"
    row = _rows(ledger.g, job)[0]
    want = 20_000 / 1e6 * settings.faultline_llm_usd_per_mtok_in + 2_000 / 1e6 * settings.faultline_llm_usd_per_mtok_out
    assert row["state"] == "failed" and row["usd"] == pytest.approx(want)


def test_brain_ask_with_the_llm_is_budgeted_before_and_costed_after(ledger, monkeypatch):
    from faultline.brain import ask as brain

    def fake_ask(question, tenant, llm, user=None, session=None, usage=None):
        usage.update(input_tokens=5_000, output_tokens=500)
        return types.SimpleNamespace(as_dict=lambda: {"answer": "ok", "tenant": tenant})

    monkeypatch.setattr(brain, "ask", fake_ask)
    monkeypatch.setattr(api.uuid, "uuid4", lambda: types.SimpleNamespace(hex=f"t{ledger.tag}askxxxxxxxxxx"))
    ledger.room(0.15)                                   # one 0.1 question fits, a second would not until settled
    with TestClient(api.app) as c:
        assert c.post("/api/brain/ask?tenant=acme", json={"question": "who owns payment?", "llm": "anthropic"}).status_code == 200
        row = _rows(ledger.g, f"t{ledger.tag}ask")[0]
        assert row["state"] == "settled" and row["usd"] == pytest.approx(5_000 / 1e6 * settings.faultline_llm_usd_per_mtok_in
                                                                          + 500 / 1e6 * settings.faultline_llm_usd_per_mtok_out)
        ledger.room(0.0)                                # the hour is spent: refused BEFORE any model call
        r = c.post("/api/brain/ask?tenant=acme", json={"question": "who owns payment?", "llm": "anthropic"})
        assert r.status_code == 429 and "budget" in r.text


def _fake_groups(monkeypatch, tag: str, outcomes: list):
    """A two-incident job without investigating anything: prepare returns two INTAKE groups, investigate_all drives the
    API's hooks in the product order (on_open, then on_start/on_done per incident) and stops where on_start raises."""
    from faultline import scenario
    from faultline.agent import loop

    class Inv:
        name = "fake-llm"

        def __init__(self):
            self.usage = {"input_tokens": 30_000, "output_tokens": 3_000}

    graph = f"eval_acme_t{tag}"
    grps = [types.SimpleNamespace(incident_id=f"inc-t{tag}-{k}", run_id=f"run-t{tag}-{k}", symptoms=["checkout"])
            for k in (1, 2)]
    p = types.SimpleNamespace(graph=graph, tenant="acme", groups=grps, run_id=grps[0].run_id,
                              incident_id=grps[0].incident_id, onset_ms=0, scenario={})

    async def fake_all(p_, inv, on_open=None, on_done=None, on_start=None, **_kw):  # M19: + on-call home and trust
        on_open(1, grps)
        out = []
        for grp, outcome in zip(grps, outcomes):
            on_start(grp)
            res = types.SimpleNamespace(incident_id=grp.incident_id, outcome=outcome, cause_id=None, error=None)
            on_done(grp, res)
            out.append(res)
        return out

    monkeypatch.setattr(loop, "LLMInvestigator", Inv)
    monkeypatch.setattr(scenario, "prepare", lambda *a, **k: p)
    monkeypatch.setattr(scenario, "investigate_all", fake_all)
    return p, grps


def _index(tag: str) -> dict:
    a = gc.engine().select_graph(audit_graph("acme"))
    rows = a.query("MATCH (x:RunIndex) WHERE x.id STARTS WITH $p RETURN x.id, x.outcome", {"p": f"run-t{tag}"}).result_set
    return dict(rows)


def _cleanup(tag: str) -> None:
    from faultline.graph import copy as gcopy

    gc.engine().select_graph(audit_graph("acme")).query("MATCH (x:RunIndex) WHERE x.id STARTS WITH $p DELETE x",
                                                        {"p": f"run-t{tag}"})
    gcopy.delete_if_exists(gc.engine(), f"eval_acme_t{tag}")


def test_a_multi_incident_llm_job_reserves_one_estimate_per_incident(ledger, monkeypatch):
    p, grps = _fake_groups(monkeypatch, ledger.tag, ["CONFIRMED", "CONFIRMED"])
    ledger.room(5.0)
    job = f"t{ledger.tag}-two"
    try:
        lid = api._reserve_llm("run", job, "acme")
        api._jobs[job] = {"state": "running"}
        api._run_job(job, "S14", "anthropic", lid)
        assert api._jobs.pop(job)["state"] == "done"
        rows = _rows(ledger.g, job)
        assert [r["id"] for r in rows] == [f"llm-run-{job}", f"llm-run-{job}-2"]   # the second incident reserved its own
        want = 30_000 / 1e6 * settings.faultline_llm_usd_per_mtok_in + 3_000 / 1e6 * settings.faultline_llm_usd_per_mtok_out
        assert all(r["state"] == "settled" for r in rows)                          # nothing stays in flight
        assert sum(r["usd"] for r in rows) == pytest.approx(want)                  # the job's real total, once
    finally:
        _cleanup(ledger.tag)


def test_a_job_that_stops_marks_every_incident_not_yet_run_failed(ledger, monkeypatch):
    """Room for one estimate only: the second incident cannot reserve, so the job stops before it. That incident is
    indexed FAILED with the reason (never RUNNING forever) and the first keeps its own outcome."""
    p, grps = _fake_groups(monkeypatch, ledger.tag, ["CONFIRMED", "CONFIRMED"])
    est = settings.faultline_llm_reserve_usd_run
    ledger.room(est * 1.5)
    job = f"t{ledger.tag}-stop"
    try:
        lid = api._reserve_llm("run", job, "acme")
        api._jobs[job] = {"state": "running"}
        api._run_job(job, "S14", "anthropic", lid)
        out = api._jobs.pop(job)
        assert out["state"] == "failed" and "not investigated" in out["error"] and "budget" in out["error"]
        assert [e["outcome"] for e in out["incidents"]] == ["CONFIRMED", "FAILED"]
        assert "not investigated" in out["incidents"][1]["error"]
        assert _index(ledger.tag) == {grps[0].run_id: "CONFIRMED", grps[1].run_id: "FAILED"}
        assert [r["state"] for r in _rows(ledger.g, job)] == ["failed"]           # only the first was reserved
    finally:
        _cleanup(ledger.tag)
