"""Live, M15 #3: a reviewer answers a contradiction for one change. An intentional override takes that decision out
of G8's violations for that change (shown as an accepted deviation, who and why); accidental keeps it; the override is
two-step over the API (plan hash) and never touches another change."""

import uuid

import anyio
import pytest
from fastapi.testclient import TestClient

from faultline import api, scenario
from faultline.agent.loop import BaselineInvestigator, run_incident
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture
def room():
    p = scenario.prepare("S1", tag=uuid.uuid4().hex[:8], set_mode=False)
    yield p
    gcopy.delete_if_exists(client.engine(), p.graph)


def _g8(p):
    r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms, symptoms=p.symptoms,
                                       investigator=BaselineInvestigator(), graph=p.graph, run_id=p.run_id,
                                       window_min=p.scenario.get("window_min")))
    return r, next(c for c in r.gate["checks"] if c["name"] == "G8 contradiction")


def _cause_and_decisions(p):
    cause = next(x["change"] for x in p.scenario["inject"] if x["change"].startswith("D-pay"))
    rows = RO(p.tenant, p.graph).run("Q-DEC-1", {"change": cause}).rows
    return cause, sorted({r["decision"] for r in rows})


def _actual(p, cause, decision):
    return next(r["actual_text"] for r in RO(p.tenant, p.graph).run("Q-DEC-1", {"change": cause}).rows
                if r["decision"] == decision)


def test_intentional_override_becomes_an_accepted_deviation(room):
    cause, decisions = _cause_and_decisions(room)
    assert len(decisions) >= 2
    keep, waive = decisions[0], decisions[1]
    writes.record_override(client.engine().select_graph(room.graph), decision=waive, change=cause, verdict="intentional",
                           by="p-030", why="timeout raised on purpose for the provider migration", plan_hash="h",
                           actual=_actual(room, cause, waive))
    r, g8 = _g8(room)
    assert r.cause_id == cause                                           # the verdict never depends on G8
    assert f"violates {keep}" in g8["detail"] and f"violates {waive}" not in g8["detail"]
    assert f"accepted deviation from {waive}" in g8["detail"] and "p-030" in g8["detail"]
    tok = context.bind(room.tenant, run_id=None, graph=room.graph, record=False)
    try:
        rows = {x["decision"]: x for x in T.decision_check(change_id=cause)["rows"]}
    finally:
        context.unbind(tok)
    assert rows[waive]["overridden"] and rows[waive]["violated_raw"] and rows[waive]["violated"] is False
    assert rows[keep]["violated"] and not rows[keep]["overridden"]


def test_accidental_keeps_the_violation_and_names_the_answer(room):
    cause, decisions = _cause_and_decisions(room)
    writes.record_override(client.engine().select_graph(room.graph), decision=decisions[0], change=cause,
                           verdict="accidental", by="p-030", why="nobody meant to drop the retries", plan_hash="h",
                           actual=_actual(room, cause, decisions[0]))
    _, g8 = _g8(room)
    assert f"violates {decisions[0]}" in g8["detail"] and "(accidental: nobody meant to drop the retries)" in g8["detail"]


def test_override_api_is_two_step_and_refuses_a_changed_reason():
    with TestClient(api.app) as c:
        r = c.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
        job = r["job"]
        for _ in range(120):
            j = c.get(f"/api/jobs/{job}").json()
            if j.get("incident") and j.get("state") != "running":
                break
            anyio.run(anyio.sleep, 0.5)
        inc = j["incident"]
        assert c.get(f"/api/incidents/{inc}").status_code == 200
        loc = api._locate(inc, "acme")
        cause, decisions = _cause_and_decisions(type("P", (), {"tenant": "acme", "graph": loc["graph"],
                                                               "scenario": scenario.load("S1")})())
        body = {"change": cause, "verdict": "intentional", "why": "agreed in the incident review", "incident": inc}
        step1 = c.post(f"/api/decisions/{decisions[0]}/override", json=body).json()
        assert step1["plan_hash"] and step1["step"].startswith("review") and step1["contradiction"]["actual"] is not None
        bad = c.post(f"/api/decisions/{decisions[0]}/override",
                     json=body | {"why": "something else", "plan_hash": step1["plan_hash"], "approver": "p-030"})
        assert bad.status_code == 409                                    # choosing ≠ approving: the hash binds the reason
        ok = c.post(f"/api/decisions/{decisions[0]}/override",
                    json=body | {"plan_hash": step1["plan_hash"], "approver": "p-030"}).json()
        assert ok["step"] == "recorded" and ok["override"].startswith("ovr-")
        again = c.post(f"/api/decisions/{decisions[0]}/override", json=body).json()
        assert again["current_override"]["verdict"] == "intentional" and again["current_override"]["by"] == "p-030"
        gcopy.delete_if_exists(client.engine(), loc["graph"])


def test_an_override_given_for_another_value_does_not_count(room):
    """Bound to the asserted value: approve "5000 is intentional", then the change asserts something else."""
    cause, decisions = _cause_and_decisions(room)
    writes.record_override(client.engine().select_graph(room.graph), decision=decisions[0], change=cause,
                           verdict="intentional", by="p-030", why="agreed for the old value", plan_hash="h",
                           actual="999999")
    tok = context.bind(room.tenant, run_id=None, graph=room.graph, record=False)
    try:
        row = next(x for x in T.decision_check(change_id=cause)["rows"] if x["decision"] == decisions[0])
    finally:
        context.unbind(tok)
    assert row["override"] is None and row["violated"] and not row["overridden"]
