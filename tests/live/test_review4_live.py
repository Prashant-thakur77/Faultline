"""Live: review round 4. Intent leases and conditional verdicts (M5, both race orders and a takeover mid-flight),
server-issued brain sessions (M1, m10), public brain questions in a bounded scratch copy (M2), the live stack's own
graph collection and memory shedding (M3), the shared warehouse mode on the public demo (M4), the unbounded own-reach
BFS (m1), forget's truncation / TOCTOU / turn redaction (m3), re-arm by copy-then-swap (m6), startup reconcile for every
tenant (m7) and GET /api/jobs/{job} (UI token)."""

from __future__ import annotations

import time
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient

from faultline import api, scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.actions import reconcile
from faultline.agent.loop import BaselineInvestigator
from faultline.agent.state import Stage
from faultline.agent.weights import weights
from faultline.brain import scratch as brain_scratch
from faultline.brain.ask import ask
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.memory import forget

pytestmark = pytest.mark.live


# ------------------------------------------------------------------ M5: intent leases
@pytest.fixture
def hero():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    assert res.outcome == "CONFIRMED" and res.post_gate
    s = scenario.load("S1")
    world = {"symptom": "checkout", "onset_ms": p.onset_ms, "effects": scenario.effects_of(s, p.onset_ms),
             "at_ms": p.onset_ms + 5 * 60_000}
    yield p, res, gh.client(p.graph), world
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _approved(p, res, hub, owner):
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id, owner)
    o = next(o for o in res.post_gate["options"] if o["kind"] == "flip_flag" and o["enabled"])
    spec = act.choose(c, o["id"], hub)
    assert act.approve(c, o["id"], spec["plan_hash"], "p-030")["mine"]
    return c, o["id"]


def _state(c, aid):
    it = c.ro().run("Q-ACT-INTENT", {"inc": c.inc, "aid": aid}).rows[0]
    a = next(a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid)
    return {"stage": c.ro().run("Q-INC-1", {"inc": c.inc}).rows[0]["stage"], "intent": it["intent_state"],
            "lease_by": it["lease_by"], "verdict": a["verdict"], "status": a["status"]}


def _stage_notes(c):
    return [r["note"] for r in c.ro().run("Q-RUN-1", {"run": c.run}).rows]


def _expire(c, aid) -> None:
    """The lease ran out (test setup: its end is moved into the past on the engine's own record; the reconciler then
    judges it on the engine clock, as in production)."""
    c.g().query("MATCH (a:Action {id:$aid}) MATCH (it:Intent) WHERE it.idem = a.idem SET it.lease_until = 1",
                {"aid": aid})


def test_the_reconciler_skips_a_leased_intent_and_the_job_never_overwrites_a_takeover(hero):
    """Race order 1: the reconciler settles first. While the execute job holds the lease the reconciler skips the
    intent; once the lease has expired it takes it over (absent at GitHub → NOT_APPLIED, intent FAILED, back to
    AWAITING_APPROVAL). The job then resumes: it writes no verdict and does not move the stage (no FAILED)."""
    p, res, hub, world = hero
    c, aid = _approved(p, res, hub, owner="act-test-job")
    assert _state(c, aid)["lease_by"] == "act-test-job"
    assert reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0) == []  # leased: skipped
    _expire(c, aid)
    out = reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0)
    assert [o["verdict"] for o in out] == ["NOT_APPLIED"]
    after = _state(c, aid)
    assert after["intent"] == "FAILED" and after["stage"] == "AWAITING_APPROVAL" and ":reconcile-" in after["lease_by"]
    notes = len(_stage_notes(c))
    api._act_job(c, {"graph": p.graph, "run": p.run_id, "scenario": "S1"}, aid)  # the job resumes, too late
    final = _state(c, aid)
    assert final == after  # same verdict, intent, stage
    assert len(_stage_notes(c)) == notes  # and not one stage event from the job


def test_the_job_settles_first_and_the_reconciler_writes_nothing(hero):
    """Race order 2: the execute job settles first (APPLIED, COMMITTED, RESOLVED). A reconciler, even after the lease,
    finds nothing PENDING; and any verdict or stage write bound to another owner matches nothing."""
    p, res, hub, world = hero
    c, aid = _approved(p, res, hub, owner="act-test-job")
    api._act_job(c, {"graph": p.graph, "run": p.run_id, "scenario": "S1"}, aid)
    done = _state(c, aid)
    assert done["stage"] == "RESOLVED" and done["intent"] == "COMMITTED" and done["verdict"] == "APPLIED"
    _expire(c, aid)
    assert reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0) == []
    with pytest.raises(writes.IntentNotPending):
        writes.record_verdict(c.g(), aid=aid, verdict="NOT_APPLIED", why="late reconciler", channels={},
                              owner="reconcile-late")
    with pytest.raises(writes.IntentNotPending):  # also with no owner at all: the intent is no longer PENDING
        writes.record_verdict(c.g(), aid=aid, verdict="UNKNOWN", why="late", channels={})
    assert not writes.advance_stage(c.g(), inc=c.inc, run=c.run, stage=Stage.FAILED.value, ord_=99, force=True,
                                    aid=aid, owner="reconcile-late", settled=True)
    assert _state(c, aid) == done


def test_a_takeover_between_execute_and_verify_stops_the_job(hero):
    """The job executed (PR merged) and stalled past its lease; the reconciler took over and settled it (found at main,
    verified APPLIED, write-back verified). The job's heartbeat and its verdict both fail: exactly one write-back."""
    p, res, hub, world = hero
    c, aid = _approved(p, res, hub, owner="act-test-job")
    act.execute(c, aid, hub)
    _expire(c, aid)
    out = reconcile.reconcile(p.tenant, p.graph, hub, lambda inc: world, older_than_ms=0)
    assert [(o["found"], o["verdict"]) for o in out] == [("at_main", "APPLIED")]
    settled = _state(c, aid)
    assert settled["stage"] == "RESOLVED" and settled["intent"] == "COMMITTED"
    with pytest.raises(writes.IntentNotPending):
        act.renew(c, aid)
    with pytest.raises(writes.IntentNotPending):
        act.verify(c, aid, hub, **world)
    assert _state(c, aid) == settled
    pms = c.g().ro_query("MATCH (pm:Postmortem {incident_id: $i}) RETURN count(pm)", {"i": c.inc}).result_set[0][0]
    assert pms == 1


# ------------------------------------------------------------------ M1 / m10: sessions
def _cleanup_sessions(user: str, graph: str = "tenant_acme") -> None:
    gclient.engine().select_graph(graph).query(
        "MATCH (s:Session {user:$u}) OPTIONAL MATCH (s)-[:HAS_TURN]->(t:Turn) DETACH DELETE s, t", {"u": user})


def test_a_session_can_never_take_a_component_id():
    user = f"u-{uuid.uuid4().hex[:6]}"
    try:
        a = ask("Who has worked on checkout?", "acme", user=user, session="checkout")
        assert a.session == "sess-checkout"
        n = gclient.engine().select_graph("tenant_acme").ro_query(
            "MATCH (n:Node {id: 'checkout'}) RETURN count(n), collect(labels(n))").result_set[0]
        assert n[0] == 1 and "Session" not in n[1][0]
    finally:
        _cleanup_sessions(user)


def test_the_turn_write_refuses_an_id_another_node_has():
    db = gclient.engine()
    room = f"eval_acme_sess_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", room)
    try:
        g = db.select_graph(room)
        g.query("CREATE (:Service:Node {id: 'sess-clash'})")
        with pytest.raises(writes.SessionError):
            writes.append_turn(g, session="sess-clash", user="u1", role="user", text="x")
        assert g.ro_query("MATCH (n:Node {id: 'sess-clash'}) RETURN count(n)").result_set[0][0] == 1
    finally:
        gcopy.delete_if_exists(db, room)


def test_another_users_session_is_403_not_500():
    api._rate.clear()
    u1, u2, sess = f"u-{uuid.uuid4().hex[:6]}", f"u-{uuid.uuid4().hex[:6]}", f"s-{uuid.uuid4().hex[:6]}"
    try:
        with TestClient(api.app) as c:
            assert c.post("/api/brain/ask", json={"question": "who knows payment?", "user": u1, "session": sess}).status_code == 200
            r = c.post("/api/brain/ask", json={"question": "who knows payment?", "user": u2, "session": sess})
            assert r.status_code == 403 and "another user" in r.json()["detail"]
    finally:
        _cleanup_sessions(u1)
        _cleanup_sessions(u2)


# ------------------------------------------------------------------ M2: public brain questions in a scratch copy
@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(settings, "faultline_public", True)
    monkeypatch.setattr(settings, "faultline_admin_key", "admin-test-key-0123456789")
    api._rate.clear()
    brain_scratch.invalidate("acme")
    with TestClient(api.app) as c:
        yield c
    brain_scratch.invalidate("acme")


def _brain_runs(graph: str) -> int:
    return gclient.engine().select_graph(graph).ro_query("MATCH (r:Run {mode:'brain'}) RETURN count(r)").result_set[0][0]


def test_public_brain_questions_never_write_the_tenant_graph(public, monkeypatch):
    c = public
    user = f"visitor-{uuid.uuid4().hex[:8]}"
    before = _brain_runs("tenant_acme")
    r = c.post("/api/brain/ask", json={"question": "What breaks if payment goes down?", "user": user})
    assert r.status_code == 200 and r.json()["guard"]["ok"], r.text  # the guard read the copy the run was recorded in
    assert _brain_runs("tenant_acme") == before
    gens = brain_scratch.generations("acme")
    assert len(gens) == 1
    g = gclient.engine().select_graph(gens[0])
    assert g.ro_query("MATCH (:Run {id:$r})-[:HAS_TOOL_CALL]->(tc) RETURN count(tc)", {"r": r.json()["run_id"]}).result_set[0][0] > 0
    hist = c.get("/api/brain/history", params={"user": user}).json()["turns"]
    assert len(hist) == 2  # the visitor's own turns, read from the same copy
    # bounded: once the copy holds scratch_max_runs runs it is replaced and the old one collected
    monkeypatch.setitem(weights()["brain"], "scratch_max_runs", 1)
    assert c.post("/api/brain/ask", json={"question": "Who has worked on cart?"}).status_code == 200
    now = brain_scratch.generations("acme")
    assert len(now) == 1 and now[0] != gens[0]
    # the operator (admin key) still records in the tenant graph
    r2 = c.post("/api/brain/ask", json={"question": "Who has worked on cart?"},
                headers={"X-Faultline-Admin-Key": "admin-test-key-0123456789"})
    assert r2.status_code == 200 and _brain_runs("tenant_acme") == before + 1
    gclient.engine().select_graph("tenant_acme").query(
        "MATCH (r:Run {id:$r}) OPTIONAL MATCH (r)-[:HAS_TOOL_CALL]->(tc) OPTIONAL MATCH (tc)-[:PRODUCED_EVIDENCE]->(e) "
        "DETACH DELETE r, tc, e", {"r": r2.json()["run_id"]})


def test_rearm_retires_the_brain_copies(public):
    c = public
    assert c.post("/api/brain/ask", json={"question": "Who has worked on cart?"}).status_code == 200
    assert brain_scratch.generations("acme")
    assert c.post("/api/demo/rearm").status_code == 200
    assert brain_scratch.generations("acme") == []


# ------------------------------------------------------------------ M3: collection and memory shedding
def test_the_api_collects_its_old_run_graphs_but_never_a_running_jobs():
    db = gclient.engine()
    old, running, other = ("eval_acme_api_v2_zz_1_aaaaaaaa", "eval_acme_api_v2_zz_2_bbbbbbbb",
                           "eval_acme_cli_v2_zz_3_cccccccc")
    for gname in (old, running, other):
        db.select_graph(gname).query("CREATE (:X {id: 1})")
    api._jobs["bbbbbbbb"] = {"state": "running", "tenant": "acme", "scenario": "S1"}
    try:
        out = api.gc_run_graphs("acme")
        names = set(db.list_graphs())
        assert old in out["deleted"] and old not in names
        assert running in names and other in names
    finally:
        api._jobs.pop("bbbbbbbb", None)
        for gname in (old, running, other):
            gcopy.delete_if_exists(db, gname)


def test_runs_are_shed_under_memory_pressure(monkeypatch):
    from faultline.graph import engine_info

    real = engine_info.memory_pressure()
    assert real["maxmemory"] > 0 and 0 <= real["fraction"] < 1  # the pinned deploy sets maxmemory
    monkeypatch.setattr(engine_info, "memory_pressure", lambda: {"used_memory": 99, "maxmemory": 100, "fraction": 0.99})
    api._rate.clear()
    r = TestClient(api.app).post("/api/scenarios/S1/run", json={"llm": "baseline"})
    assert r.status_code == 429 and "memory" in r.json()["detail"]


# ------------------------------------------------------------------ M4: the shared warehouse on the public demo
def test_public_data_run_needing_another_mode_is_refused_while_one_is_active(public):
    held = scenario.WAREHOUSE.reserve(scenario.load("S2")["pipeline_mode"])  # an S2 run is reading the warehouse
    try:
        r = public.post("/api/scenarios/S4D/run", json={"llm": "baseline"})
        assert r.status_code == 429 and "warehouse" in r.json()["detail"] and "mode" in r.json()["detail"]
    finally:
        held.release()


# ------------------------------------------------------------------ m1: own reach at any depth
def test_bfs_max_level_minus_one_is_unbounded_on_the_pinned_engine(scratch):
    scratch.query("UNWIND range(0, 20) AS i CREATE (:N {id: i})")
    scratch.query("MATCH (a:N), (b:N) WHERE b.id = a.id + 1 CREATE (a)-[:P]->(b)")
    q = "MATCH (s:N {id: 0}) CALL algo.BFS(s, $lvl, 'P') YIELD nodes RETURN size(nodes)"
    assert scratch.ro_query(q, {"lvl": 8}).result_set[0][0] == 8
    assert scratch.ro_query(q, {"lvl": -1}).result_set[0][0] == 20  # the 20-hop chain, all of it
    from faultline.graph.templates import load

    assert "(mo, -1, 'PROPAGATES_TO')" in load("Q-VERIFY-ALLOW").text


# ------------------------------------------------------------------ m3: forget
@pytest.fixture
def room():
    db = gclient.engine()
    name = f"eval_acme_forgetrace_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", name)
    yield name
    gcopy.delete_if_exists(db, name)


def test_forget_refuses_when_another_doc_produced_a_listed_node_since_the_dry_run(room, monkeypatch):
    g = gclient.engine().select_graph(room)
    dry = forget.dry_run("acme", "doc-adr-004", graph=room)
    assert dry["owned"]
    real_dry = forget.dry_run

    def racing_dry_run(tenant, doc, graph=None):  # the execute's own re-read passes, then another doc lands
        out = real_dry(tenant, doc, graph)
        g.query("MATCH (n:Node {id: $id}) CREATE (:Doc:Node {id: 'doc-race'})-[:PRODUCED]->(n)", {"id": out["owned"][0]["id"]})
        return out

    monkeypatch.setattr(forget, "dry_run", racing_dry_run)
    with pytest.raises(forget.ForgetRefused):
        forget.execute("acme", "doc-adr-004", dry["token"], "p-030", graph=room)
    left = g.ro_query("MATCH (d:Doc {id: 'doc-adr-004'}) RETURN count(d)").result_set[0][0]
    assert left == 1  # nothing deleted


def test_forget_fails_loudly_when_the_dry_run_list_is_truncated(room):
    g = gclient.engine().select_graph(room)
    g.query("CREATE (d:Doc:Node {id: 'doc-big'}) WITH d UNWIND range(1, 101) AS i "
            "CREATE (d)-[:PRODUCED]->(:Runbook:Node {id: 'rb-big-' + toString(i)})")
    with pytest.raises(forget.ForgetRefused, match="more nodes than the dry run can list"):
        forget.dry_run("acme", "doc-big", graph=room)


def test_forget_redacts_turns_that_cited_what_was_forgotten(room):
    g = gclient.engine().select_graph(room)
    dry = forget.dry_run("acme", "doc-adr-004", graph=room)
    cited = dry["owned"][0]["id"]
    writes.append_turn(g, session="sess-redact", user="u1", role="assistant", text=f"Decision [{cited}] says so.",
                       refs=[cited, "checkout"])
    out = forget.execute("acme", "doc-adr-004", dry["token"], "p-030", graph=room)
    assert out["turns_redacted"] == 1
    t = g.ro_query("MATCH (:Session {id:'sess-redact'})-[:HAS_TURN]->(t:Turn) RETURN t.text, t.refs").result_set[0]
    assert cited not in t[0] and t[1] == ["checkout"]


# ------------------------------------------------------------------ m6: re-arm copies then swaps
def test_rearm_swaps_a_fresh_copy_in_with_one_rename():
    db = gclient.engine()
    out = gcopy.rearm(db, "acme", reason="test-swap")
    assert out["dst"] == "tenant_acme" and out["via"].startswith("scratch_acme_rearm_")
    names = set(db.list_graphs())
    assert "tenant_acme" in names and not any(n.startswith("scratch_acme_rearm_") for n in names)
    g = db.select_graph("tenant_acme")
    assert g.ro_query("MATCH (m:Meta) RETURN m.ready").result_set[0][0]
    idx = lambda name: db.select_graph(name).ro_query("CALL db.indexes() YIELD label RETURN count(label)").result_set[0][0]  # noqa: E731
    assert idx("tenant_acme") == idx("golden_acme")


# ------------------------------------------------------------------ m7: startup reconcile for every tenant
def test_startup_reconcile_reads_every_tenants_run_index(monkeypatch):
    assert {"acme", "globex"} <= set(api._configured_tenants())
    seen = []

    class Rec:
        def __init__(self, tenant, graph=None, **kw):
            seen.append((tenant, graph))

        def run(self, tid, params):
            return type("R", (), {"rows": []})()

    monkeypatch.setattr(api, "RO", Rec)
    api._startup_reconcile()
    assert ("acme", "audit_acme") in seen and ("globex", "audit_globex") in seen


# ------------------------------------------------------------------ UI token: the job's incidents, token to its holder
def test_job_status_lists_the_jobs_incidents_and_echoes_the_token_only_to_its_holder(public):
    c = public
    r = c.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
    job, token, graph = r["job"], r["run_token"], r["graph"]
    try:
        anon = c.get(f"/api/jobs/{job}?tenant=acme").json()
        assert anon["token_valid"] is False and "run_token" not in anon and anon["incident"] == r["incident"]
        mine = c.get(f"/api/jobs/{job}?tenant=acme", headers={"X-Faultline-Run-Token": token}).json()
        assert mine["token_valid"] is True and mine["run_token"] == token
        assert c.get(f"/api/jobs/{job}?tenant=globex").status_code == 404
    finally:
        t0 = time.time()
        while api._jobs.get(job, {}).get("state") == "running" and time.time() - t0 < 120:
            time.sleep(0.3)
        gcopy.delete_if_exists(gclient.engine(), graph)
