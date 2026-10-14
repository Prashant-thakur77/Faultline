"""Live: review round 5. Intent leases on the engine clock with boot epochs, the periodic reconciler and pre-execute
failures (M1, minors 1-3), a data repair tied to its incident's warehouse state (M2) that never outlives its run (M3),
the collector's holds, 410 and the SSE `collected` event (M5), the simulated world after a restart (minor 8), brain
scratch copies (minor 5) and re-arm (minor 10)."""

from __future__ import annotations

import inspect
import json
import time
import uuid
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from faultline import api, repair, scenario, warehouse
from faultline.actions import act, boot, reconcile
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator
from faultline.brain import scratch as brain_scratch
from faultline.brain.ask import ask
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
STG = "pipeline/transforms/stg_orders.sql"


@pytest.fixture
def hero():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    assert res.outcome == "CONFIRMED" and res.post_gate
    s = scenario.load("S1")
    world = {"symptom": "checkout", "onset_ms": p.onset_ms, "effects": scenario.effects_of(s, p.onset_ms),
             "at_ms": p.onset_ms + 5 * 60_000}
    yield p, res, gh.client(p.graph), world
    gh.reset_sim(p.graph)
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _approved(p, res, hub, owner):
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id, owner)
    o = next(o for o in res.post_gate["options"] if o["kind"] == "flip_flag" and o["enabled"])
    spec = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030")["mine"]
    return c, o["id"], spec


def _intent(c, aid) -> dict:
    return c.ro().run("Q-ACT-INTENT", {"inc": c.inc, "aid": aid}).rows[0]


def _set_intent(c, aid, **props) -> None:
    """Test setup only: put the intent into the state a crash leaves behind (a dead boot's lease, an expired lease)."""
    for k, v in props.items():
        assert k in ("lease_boot", "lease_until", "created_boot")
        c.g().query(f"MATCH (a:Action {{id:$aid}}) MATCH (it:Intent) WHERE it.idem = a.idem SET it.{k} = $v",
                    {"aid": aid, "v": v})


def _notes(c) -> list[str]:
    return [r["note"] for r in c.ro().run("Q-RUN-1", {"run": c.run}).rows]


# ------------------------------------------------------------------ M1 / minor 1: engine clock, boot epochs
def test_lease_judgements_use_only_the_engine_clock():
    assert "now_ms" not in inspect.signature(reconcile.reconcile).parameters
    q = RO("acme").run  # the templates themselves
    from faultline.graph.templates import load

    for tid in ("Q-INTENT-1", "Q-ACT-INTENT", "Q-BOOT-LIVE", "Q-GC-HOLD"):
        assert "timestamp()" in load(tid).text and "$now" not in load(tid).text
    assert "timestamp()" in writes.W_INTENT_CLAIM and "$now" not in writes.W_INTENT_CLAIM
    assert q


def test_a_dead_boots_lease_is_taken_over_at_once_and_a_live_ones_is_not(hero):
    p, res, hub, world = hero
    c, aid, _ = _approved(p, res, hub, owner=f"{boot.BOOT_ID}:act-test")
    dead = f"boot-dead{uuid.uuid4().hex[:8]}"
    _set_intent(c, aid, lease_boot=dead)  # the API that approved it was killed; its lease still runs for 5 minutes
    assert _intent(c, aid)["lease_live"]
    writes.boot_beat(gclient.engine().select_graph("audit_acme"), boot=dead, pid=1, role="api")  # ...but it beats
    assert reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0) == []  # alive: skipped
    writes.boot_end(gclient.engine().select_graph("audit_acme"), boot=dead)  # now it is gone (ended, or stale)
    out = reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0)
    assert [(o["found"], o["verdict"]) for o in out] == [("absent", "NOT_APPLIED")]  # taken over without waiting
    assert _intent(c, aid)["intent_state"] == "FAILED"


def test_the_periodic_pass_settles_a_crashed_jobs_intent(hero):
    """The execute job merged the PR and its process died: the API's periodic reconcile (no approval needed, real
    clock) takes the dead boot's lease and settles the intent once: APPLIED, written back, RESOLVED."""
    p, res, hub, world = hero
    c, aid, _ = _approved(p, res, hub, owner=f"{boot.BOOT_ID}:act-test")
    act.execute(c, aid, hub)
    _set_intent(c, aid, lease_boot=f"boot-dead{uuid.uuid4().hex[:8]}")
    audit = gclient.engine().select_graph("audit_acme")
    writes.index_run(audit, run=p.run_id, inc=p.incident_id, graph=p.graph, scenario="S1", tenant="acme",
                     investigator="test")
    assert api._reconcile_all("periodic") >= 1
    it = _intent(c, aid)
    assert it["intent_state"] == "COMMITTED" and it["stage"] == "RESOLVED"
    assert any(n.startswith("reconciled (at_main); write-back verified") for n in _notes(c))
    assert api._reconcile_all("periodic") == 0 or _intent(c, aid)["intent_state"] == "COMMITTED"


# ------------------------------------------------------------------ minor 2: fencing
def test_execute_refuses_an_expired_lease_before_touching_github(hero):
    p, res, hub, world = hero
    c, aid, spec = _approved(p, res, hub, owner=f"{boot.BOOT_ID}:act-test")
    _set_intent(c, aid, lease_until=1)
    with pytest.raises(writes.IntentNotPending, match="expired"):
        act.execute(c, aid, hub)
    assert hub.find_pr(spec["args"]["repo"], spec["branch"]) is None


# ------------------------------------------------------------------ minor 3: a pre-execute failure
def test_a_failure_before_execute_fails_the_intent_with_the_stage_and_is_never_resurrected(hero):
    p, res, hub, world = hero
    c, aid, spec = _approved(p, res, hub, owner=f"{boot.BOOT_ID}:act-test")
    api._act_job(c, {"graph": p.graph, "run": p.run_id, "scenario": None}, aid)  # no second channel: refused early
    it = _intent(c, aid)
    assert it["intent_state"] == "FAILED" and it["stage"] == "FAILED"
    assert any(n.startswith("not executed: NotExecuted: no second verification channel") for n in _notes(c))
    assert reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0) == []
    assert _intent(c, aid)["stage"] == "FAILED" and hub.find_pr(spec["args"]["repo"], spec["branch"]) is None


# ------------------------------------------------------------------ minor 8: the simulated world after a restart
def test_a_reset_simulated_world_is_unknown_never_absent_and_is_not_re_escalated(hero):
    p, res, hub, world = hero
    c, aid, _ = _approved(p, res, hub, owner=None)
    act.execute(c, aid, hub)
    _set_intent(c, aid, created_boot="boot-before-restart")
    gh.reset_sim(p.graph)  # the API restarted: its in-memory GitHub starts empty
    fresh = gh.client(p.graph)
    out = reconcile.reconcile(p.tenant, p.graph, fresh, lambda inc: world, older_than_ms=0)
    assert [(o["found"], o["verdict"]) for o in out] == [("world_reset", "UNKNOWN")]
    it = _intent(c, aid)
    assert it["intent_state"] == "PENDING" and it["stage"] == "UNKNOWN_ESCALATED"
    n = len(_notes(c))
    again = reconcile.reconcile(p.tenant, p.graph, fresh, lambda inc: world, older_than_ms=0)
    assert [o["verdict"] for o in again] == ["UNKNOWN"] and "already escalated" in again[0]["found"]
    assert len(_notes(c)) == n  # a periodic reconcile adds nothing while the answer is the same


# ------------------------------------------------------------------ M2 / M3: a data repair on its incident's own data
_CENTS_FIX = (ROOT / STG).read_text().replace(
    "    CAST(amount AS DOUBLE) AS amount,",
    "    CASE WHEN payment_processor = 'cloudpay_v2' AND CAST(order_ts AS TIMESTAMP) >= TIMESTAMP '2026-08-07 00:00:00'\n"
    "         THEN CAST(amount AS DOUBLE) / 100.0 ELSE CAST(amount AS DOUBLE) END AS amount,")
_COSMETIC = (ROOT / STG).read_text().replace("-- stg_orders: cleaned order stream.",
                                             "-- stg_orders: cleaned order stream (touched).")


@pytest.fixture
def s2():
    pristine = (ROOT / STG).read_text()
    p, res = anyio.run(lambda: scenario.run("S2", BaselineInvestigator(), set_mode=True, keep=True))
    assert res.outcome == "CONFIRMED"
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    yield p, res, c, gh.client(p.graph)
    repair.restore_pristine()
    scenario.set_pipeline_mode("incident")
    assert (ROOT / STG).read_text() == pristine
    gh.reset_sim(p.graph)
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _repair_planned(c, res, hub, sql, why):
    o = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
    args = act.propose_data_repair(c, file=STG, new_content=sql, reasoning=why)
    assert args["fixture"]["mode"] == "incident" and len(args["fixture"]["sources_sha256"]) == 64
    spec = act.choose(c, o["id"], hub)
    assert spec["args"]["fixture"] == args["fixture"]  # bound into the plan hash
    return o["id"], spec


@pytest.mark.slow
def test_an_unrelated_patch_never_verifies_applied_after_a_healthy_switch(s2):
    """A healthy-mode run switched the shared warehouse between the investigation and the approval. Before round 5 the
    verification rebuilt whatever was on disk (healthy data) and a patch that fixes nothing read APPLIED."""
    p, res, c, hub = s2
    aid, spec = _repair_planned(c, res, hub, _COSMETIC, "a cosmetic change that cannot fix the KPI")
    scenario.set_pipeline_mode("healthy")  # another run, in between
    assert warehouse.fixture_state()["mode"] == "healthy"
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    v = act.verify(c, aid, hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
    assert v["verdict"] != "APPLIED", v
    assert v["verdict"] == "NOT_APPLIED" and v["channels"]["fixture"]["mode"] == "incident", v
    assert v["channels"]["warehouse"]["mode"] == "incident"
    assert (ROOT / STG).read_text() == spec["before"]  # reverted


@pytest.mark.slow
def test_the_real_fix_verifies_on_the_incidents_data_and_does_not_outlive_the_next_mode_switch(s2):
    p, res, c, hub = s2
    aid, spec = _repair_planned(c, res, hub, _CENTS_FIX, "normalise cloudpay_v2 integer cents to dollars")
    scenario.set_pipeline_mode("healthy")
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    v = act.verify(c, aid, hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
    assert v["verdict"] == "APPLIED" and v["channels"]["fixture"]["mode"] == "incident", v
    assert (ROOT / STG).read_text() == _CENTS_FIX
    scenario.set_pipeline_mode("healthy")  # the next run: M3, the shared world goes back to pristine
    assert (ROOT / STG).read_text() == spec["before"]
    assert not list((ROOT / "pipeline" / "transforms").glob("*.orig"))


@pytest.mark.slow
def test_sources_that_cannot_be_reestablished_make_the_verdict_unknown(s2, monkeypatch):
    p, res, c, hub = s2
    aid, spec = _repair_planned(c, res, hub, _CENTS_FIX, "normalise cents")
    act.approve(c, aid, spec["plan_hash"], "p-030")
    act.execute(c, aid, hub)
    monkeypatch.setattr(warehouse, "sources_sha256", lambda: "0" * 64)  # the generator no longer reproduces them
    v = act.verify(c, aid, hub, symptom="kpi.exec_revenue", onset_ms=p.onset_ms, effects=[], at_ms=p.onset_ms)
    assert v["verdict"] == "UNKNOWN" and "cannot tie verification" in v["explanation"], v
    marker = repair.unverified_marker(ROOT / STG)
    assert marker.exists() and json.loads(marker.read_text())["incident"] == c.inc  # left applied, clearly marked
    assert _intent(c, aid)["intent_state"] == "PENDING"


@pytest.mark.slow
def test_execute_refuses_before_touching_when_the_incident_data_cannot_be_reestablished(s2, monkeypatch):
    p, res, c, hub = s2
    aid, spec = _repair_planned(c, res, hub, _CENTS_FIX, "normalise cents")
    c.owner = f"{boot.BOOT_ID}:act-test"
    act.approve(c, aid, spec["plan_hash"], "p-030")
    monkeypatch.setattr(warehouse, "sources_sha256", lambda: "0" * 64)
    api._act_job(c, {"graph": p.graph, "run": p.run_id, "scenario": "S2"}, aid)
    it = _intent(c, aid)
    assert it["intent_state"] == "FAILED" and it["stage"] == "UNKNOWN_ESCALATED"
    assert (ROOT / STG).read_text() == spec["before"]  # nothing was applied
    row = next(a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid)
    assert row["verdict"] == "UNKNOWN"


# ------------------------------------------------------------------ M5: the collector's holds, 410, `collected`
def _mk(name: str, cypher: str) -> None:
    gclient.engine().select_graph(name).query(cypher)


def test_the_collector_keeps_graphs_in_use_and_collects_idle_finished_ones():
    tag = uuid.uuid4().hex[:6]
    g = {k: f"eval_acme_api_v2_zz_{i}_{tag}{i:02d}" for i, k in enumerate(
        ("open_recent", "pending", "acting", "idle_done", "open_stale"))}
    day = 86_400_000
    _mk(g["open_recent"], "CREATE (:Incident {id:'i1', stage:'AWAITING_APPROVAL'}), (:StageEvent {id:'s', at: timestamp()})")
    _mk(g["pending"], f"CREATE (:Incident {{id:'i2', stage:'EXECUTE'}}), (:Intent {{idem:'x', state:'PENDING'}}), "
                      f"(:StageEvent {{id:'s', at: timestamp() - {2 * day}}})")
    _mk(g["acting"], f"CREATE (:Incident {{id:'i3', stage:'RESOLVED'}}), (:StageEvent {{id:'s', at: timestamp() - {day}}})")
    _mk(g["idle_done"], f"CREATE (:Incident {{id:'i4', stage:'RESOLVED'}}), (:StageEvent {{id:'s', at: timestamp() - {day}}})")
    _mk(g["open_stale"], f"CREATE (:Incident {{id:'i5', stage:'AWAITING_APPROVAL'}}), "
                         f"(:StageEvent {{id:'s', at: timestamp() - {2 * day}}})")
    api._work_enter(g["acting"])
    try:
        out = api.gc_run_graphs("acme")
        names = set(gclient.engine().list_graphs())
        assert {g["idle_done"], g["open_stale"]} <= set(out["deleted"])
        for k in ("open_recent", "pending", "acting"):
            assert g[k] in names and g[k] in out["held"], (k, out["held"])
        assert "PENDING" in out["held"][g["pending"]] and "recently" in out["held"][g["open_recent"]]
    finally:
        api._work_leave(g["acting"])
        for name in g.values():
            gcopy.delete_if_exists(gclient.engine(), name)


def test_a_collected_run_answers_410_and_its_stream_says_collected(monkeypatch):
    monkeypatch.setattr(settings, "faultline_public", False)
    api._rate.clear()
    client = TestClient(api.app)
    r = client.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
    inc, graph = r["incident"], r["graph"]
    t0 = time.time()
    while client.get(f"/api/incidents/{inc}?tenant=acme").json()["incident"]["stage"] != "AWAITING_APPROVAL" \
            or client.get(f"/api/jobs/{r['job']}?tenant=acme").json()["state"] == "running":
        assert time.time() - t0 < 120  # the job has finished writing (the collector never takes a running job's graph)
        time.sleep(0.3)
    # the endpoint's own event generator, driven directly (the test client buffers a streaming body until it ends)
    class _Req:
        client = type("C", (), {"host": "sse-test"})()

        async def is_disconnected(self) -> bool:
            return False

    async def watch() -> list[dict]:
        resp = await api.incident_events(inc, _Req(), "acme")
        seen: list[dict] = []
        async for ev in resp.body_iterator:
            seen.append(ev)
            if ev["event"] == "hello":
                gcopy.delete_if_exists(gclient.engine(), graph)  # collected while a visitor watches
            if ev["event"] in ("collected", "done", "idle") or len(seen) > 500:
                break
        return seen

    events = anyio.run(watch)
    assert events[-1]["event"] == "collected", [e["event"] for e in events]
    assert "collected" in json.loads(events[-1]["data"])["reason"]
    v = client.get(f"/api/incidents/{inc}?tenant=acme")
    assert v.status_code == 410 and "collected" in v.json()["detail"]
    assert client.get(f"/api/incidents/{inc}/events?tenant=acme").status_code == 410  # never a reconnect loop
    assert client.post(f"/api/incidents/{inc}/choose?tenant=acme", json={"action_id": "x"}).status_code == 410
    gh.reset_sim(graph)


# ------------------------------------------------------------------ minor 5: brain scratch copies
def test_brain_runs_count_only_after_the_copy_was_born():
    db = gclient.engine()
    name = f"scratch_acme_brain_{int(time.time()):010d}_{uuid.uuid4().hex[:6]}"
    gcopy.copy_graph(db, "tenant_acme", name)
    try:
        db.select_graph(name).query("CREATE (:Run:Node {id:'r-copied', mode:'brain', created_at: timestamp() - 1000})")
        assert RO("acme", name).run("Q-BRAIN-RUNS", {}).rows[0]["runs"] >= 1  # a copy that was never stamped
        writes.stamp_scratch_born(db.select_graph(name))
        assert RO("acme", name).run("Q-BRAIN-RUNS", {}).rows[0]["runs"] == 0
        ask("Who has worked on cart?", "acme", graph=name)
        assert RO("acme", name).run("Q-BRAIN-RUNS", {}).rows[0]["runs"] == 1
    finally:
        gcopy.delete_if_exists(db, name)


def test_a_rearm_in_another_process_makes_the_brain_copy_stale():
    brain_scratch.invalidate("acme")
    with brain_scratch.use("acme") as first:
        pass
    with brain_scratch.use("acme") as same:
        assert same == first  # fresh: reused
    gcopy.rearm(gclient.engine(), "acme", reason="test: another process")  # NOT the API: no invalidate() here
    try:
        with brain_scratch.use("acme") as after:
            assert after != first  # the epoch differs: a new copy of the re-armed tenant graph
        assert first not in brain_scratch.generations("acme")
    finally:
        brain_scratch.invalidate("acme")


# ------------------------------------------------------------------ minor 10: re-arm
def test_rearm_sheds_load_and_reports_an_audit_failure_as_rearmed(monkeypatch):
    from faultline.graph import engine_info

    api._rate.clear()
    client = TestClient(api.app)
    monkeypatch.setattr(engine_info, "memory_pressure", lambda: {"used_memory": 99, "maxmemory": 100, "fraction": 0.99})
    r = client.post("/api/demo/rearm")
    assert r.status_code == 429 and "memory" in r.json()["detail"]
    monkeypatch.undo()
    api._rate.clear()

    def broken(*a, **k):
        raise writes.WriteError("audit graph refused the write (simulated)")

    monkeypatch.setattr(writes, "append_audit", broken)
    r = client.post("/api/demo/rearm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "re-armed (audit write failed)" and r.json()["dst"] == "tenant_acme"
    assert RO("acme").require_ready()
