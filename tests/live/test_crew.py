"""Live: the crew records (M17) and the claim fencing they rely on.

  * a reaped and re-claimed work item refuses its stale owner's completion and renewal (epoch fencing), even when
    the new claimant has the same agent id;
  * the reaper reopens only its own run's tasks of one kind, and never crew records;
  * crew steps chain with NEXT, record failures as failed and still raise, and a resumed step is not recorded twice;
  * G7 never counts a crew record as a vote (Q-GATE-CORR reads specialist tasks only).
"""

import time

import pytest

from faultline.agent import crew
from faultline.agent.state import Stage
from faultline.graph import client, writes
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
NAME = "eval_acme_crew_probe"


@pytest.fixture()
def g():
    db = client.engine()
    gcopy.delete_if_exists(db, NAME)
    gcopy.copy_graph(db, "golden_acme", NAME)
    try:
        yield db.select_graph(NAME)
    finally:
        gcopy.delete_if_exists(db, NAME)


def _expire(g, **kw) -> int:
    n = writes.claim_epoch(g, lease_ms=1, **kw)
    time.sleep(0.02)
    return n


def test_reaped_claim_fences_the_stale_owner(g):
    n1 = _expire(g, task="w1", agent="a1", kind="specialist", run="run-x")
    assert n1 == 1
    assert writes.reap_expired(g, run="run-x", kind="specialist") == ["w1"]
    n2 = writes.claim_epoch(g, task="w1", agent="a1", kind="specialist", run="run-x")   # the same agent id, again
    assert n2 == 2
    assert not writes.renew_task(g, task="w1", agent="a1", n=n1)                         # stale epoch: refused
    assert writes.renew_task(g, task="w1", agent="a1", n=n2)
    common = dict(task="w1", agent="a1", run="run-x", role="code", status="complete", names=[], cites=[], report={})
    assert not writes.complete_specialist_task(g, **common, n=n1)                       # the late, stale completion
    assert writes.complete_specialist_task(g, **common, n=n2)                           # exactly one record
    rows = RO("acme", NAME).run("Q-CREW-1", {"run": "run-x"}).rows
    assert [r["task"] for r in rows] == ["w1"] and rows[0]["reaps"] == 1


def test_reaper_scope(g):
    _expire(g, task="x1", agent="a1", kind="specialist", run="run-x")
    _expire(g, task="y1", agent="a1", kind="specialist", run="run-y")
    assert writes.reap_expired(g, run="run-y", kind="specialist") == ["y1"]               # never another run's task
    assert writes.reap_expired(g, run="run-x", kind="other") == []                        # nor another kind
    with pytest.raises(writes.WriteError):
        writes.reap_expired(g, run="run-x", kind="crew")                                  # crew records are not locks
    with pytest.raises(writes.WriteError):
        writes.reap_expired(g, run="", kind="specialist")


def test_crew_steps_chain_fail_loudly_and_are_not_recorded_twice(g):
    kw = dict(tenant="acme", graph=NAME, run_id="run-c")
    with crew.step(key="historian", stage=Stage.RECALL, **kw) as st:
        st.summary = "recalled"
        st.tool_calls = ["no-such-call"]          # unknown ids are ignored, never invented
    with pytest.raises(RuntimeError, match="boom"):
        with crew.step(key="cartographer", stage=Stage.LOCALIZE, **kw):
            raise RuntimeError("boom")
    with crew.step(key="historian", stage=Stage.RECALL, **kw) as again:   # a resumed job re-entering a done step
        assert not again.owned
    rows = {r["role"]: r for r in RO("acme", NAME).run("Q-CREW-1", {"run": "run-c"}).rows}
    assert rows["historian"]["state"] == "done" and rows["historian"]["summary"] == "recalled"
    assert rows["historian"]["calls"] == []
    assert rows["cartographer"]["state"] == "failed" and "boom" in rows["cartographer"]["summary"]
    assert rows["cartographer"]["after"] == [rows["historian"]["task"]]   # NEXT: the hand-off order
    assert rows["historian"]["agent"] == crew.agent_id("historian")


def test_g7_never_counts_a_crew_record(g):
    # a crew step whose role happens to be a G7 role is still not a vote: Q-GATE-CORR reads specialist tasks only
    n = writes.claim_epoch(g, task="c1", agent="crew-x", kind="crew", run="run-g")
    assert writes.complete_crew_step(g, task="c1", agent="crew-x", n=n, run="run-g", role="code", stage="INVESTIGATE",
                                     stages=["INVESTIGATE"], summary="", tool_calls=[])
    rows = RO("acme", NAME).run("Q-GATE-CORR", {"run": "run-g", "roles": ["change", "code", "data"],
                                                 "cause": "D-x", "chain": []}).rows
    assert rows == []


def test_roster_tools_come_from_the_stage_whitelists():
    from faultline.agent import phases

    for m in crew.ROSTER:
        assert set(m.tools()) == {t for s in m.stages for t in phases.stage_toolset(s)}
    assert [m.model for m in crew.ROSTER if m.model != "none"] == ["optional"]   # only the lead may use a model
    assert crew.BY_KEY["gatekeeper"].model == "none"


def test_provenance_traces_the_verdict_to_the_agents_that_made_its_evidence():
    """Q-PROV-1 on a real S1 run: the confirmed cause's evidence was produced by calls that a named agent MADE (or the
    gate's own checks), and the data tools' calls are attributed too (MADE from their tool_call_id)."""
    import anyio

    from faultline import scenario
    from faultline.agent.loop import BaselineInvestigator

    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), keep=True))
    try:
        rows = RO("acme", p.graph).run("Q-PROV-1", {"inc": res.incident_id}).rows
        assert rows and {r["blames"] for r in rows} == {res.cause_id}
        assert "telemetry" in {r["role"] for r in rows if r.get("task")}
        crew_rows = RO("acme", p.graph).run("Q-CREW-1", {"run": res.run_id}).rows
        assert [r["role"] for r in crew_rows if r["kind"] == "crew"][:5] == ["triage", "historian", "cartographer", "profiler", "lead"]
    finally:
        gcopy.delete_if_exists(client.engine(), p.graph)
