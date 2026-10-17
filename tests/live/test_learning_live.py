"""Live (M21 learning): events and the state derived from them in Cypher (recency decay, Beta-smoothed preference,
RESPONDED, guidelines, gaps), the public-demo trust rule (anonymous visitors cannot poison the learned state), the
guideline override, forgetting a person's influence with a receipt, the learned MCP tools, recency-aware recall and the
A4 ablation. The learning home graph is a fresh copy of golden_acme per test; tenant_acme and oncall_acme are never
written."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.actions import oncall
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO
from faultline.mcp_server import context
from faultline.mcp_server import tools as T
from faultline.memory import learning

pytestmark = pytest.mark.live
DAY = 86_400_000


@pytest.fixture
def home(monkeypatch):
    db = gclient.engine()
    name = f"eval_acme_learntest_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", name)
    monkeypatch.setattr(oncall, "home_graph", lambda t: name)
    api._rate.clear()
    made: list[str] = [name]
    yield name, made
    for g in made:
        gcopy.delete_if_exists(db, g)


def _run(c, made, sid="S1", hdr=None):
    r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"}, headers=hdr or {}).json()
    made.append(r["graph"])
    for _ in range(600):
        j = c.get(f"/api/jobs/{r['job']}", headers=hdr or {}).json()
        if j["state"] != "running":
            break
        time.sleep(0.3)
    assert j["state"] == "done", j
    return r["incident"], r["graph"], r.get("run_token")


def _wait(c, inc, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in ("RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"):
            return st
        time.sleep(0.3)
    raise AssertionError(f"{inc} stuck at {st}")


def _flag(c, inc, hdr=None):
    return next(o for o in c.get(f"/api/incidents/{inc}/plan", headers=hdr or {}).json()["options"]
                if o["kind"] == "flip_flag" and o["enabled"])


def test_decay_responded_and_idempotent_events_are_computed_in_cypher(home):
    name, _ = home
    now = learning.now_ms()
    for k, at in enumerate((now, now - 14 * DAY)):   # one today, one a half-life ago
        learning.record("acme", eid=f"le-test-{k}", kind="approve", person="p-030", family="payment", at=at,
                        action_kind="flip_flag", incident=f"inc-{k}")
    learning.record("acme", eid="le-test-0", kind="approve", person="p-030", family="payment", at=now,
                    action_kind="flip_flag", incident="inc-0")   # the same event again: recorded once
    learning.record("acme", eid="le-test-r", kind="reject", person="p-017", family="payment", at=now,
                    action_kind="rollback_deploy", incident="inc-9", reason="never roll back on Fridays")
    ro = RO("acme", name)
    rows = {r["action_kind"]: r for r in ro.run("Q-LEARN-PREF", {"family": "payment", "now": now,
                                                                 "half_life_ms": learning.half_life_ms()}).rows}
    assert rows["flip_flag"]["n_approve"] == 2 and abs(rows["flip_flag"]["approvals"] - 1.5) < 1e-3
    assert abs(rows["flip_flag"]["pref"] - (2.5 / 3.5)) < 1e-3
    assert rows["rollback_deploy"]["n_reject"] == 1 and set(rows["flip_flag"]["events"]) == {"le-test-0", "le-test-1"}
    later = {r["action_kind"]: r for r in ro.run("Q-LEARN-PREF", {"family": "payment", "now": now + 14 * DAY,
                                                                  "half_life_ms": learning.half_life_ms()}).rows}
    assert abs(later["flip_flag"]["approvals"] - 0.75) < 1e-3   # decayed again on read, exactly
    resp = ro.run("Q-LEARN-RESP", {"target": "payment", "now": now, "half_life_ms": learning.half_life_ms()}).rows
    assert [r["person"] for r in resp] == ["p-030"] and resp[0]["approvals"] == 2 and abs(resp[0]["score"] - 1.5) < 1e-3
    gl = ro.run("Q-LEARN-GUIDE", {"family": "payment", "statuses": ["proposed"]}).rows
    assert len(gl) == 1 and gl[0]["event"] == "le-test-r" and gl[0]["by"] == "p-017" and gl[0]["status"] == "proposed"
    # promote needs an active person and the right status; dismiss after promote
    assert learning.set_guideline("acme", gl[0]["id"], "promote", "nobody-here") is None
    assert learning.set_guideline("acme", gl[0]["id"], "promote", "p-030")["status"] == "active"
    assert learning.set_guideline("acme", gl[0]["id"], "promote", "p-030") is None
    assert [g["id"] for g in learning.active_guidelines("acme", "payment", "rollback_deploy")] == [gl[0]["id"]]
    assert learning.set_guideline("acme", gl[0]["id"], "dismiss", "p-030")["status"] == "dismissed"


def test_a_public_visitor_cannot_poison_learned_state_a_keyed_run_can(home, monkeypatch):
    name, made = home
    monkeypatch.setattr(settings, "faultline_public", True)
    monkeypatch.setattr(settings, "faultline_approver_key", "test-approver-key")
    key = {"X-Faultline-Approver-Key": "test-approver-key"}
    with TestClient(api.app) as c:
        inc, graph, tok = _run(c, made)
        hdr = {"X-Faultline-Run-Token": tok}
        opt = _flag(c, inc, hdr)
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}, headers=hdr).json()
        r = c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                          "approver": "p-030"}, headers=hdr)
        assert r.status_code == 200 and r.json()["learned"]["learned"] is False
        assert "anonymous" in r.json()["learned"]["why"]
        _wait(c, inc)
        # the visitor's own page token (the run token unlocks it) acknowledges a page: not learned either
        pages = c.get(f"/api/pages?incident={inc}").json()["rows"]
        st = c.get("/api/learned").json()
        assert st["events"]["rows"] == [] and st["preferences"]["rows"] == [] and st["responders"]["rows"] == []
        # changing learned state needs the approver key on the public demo
        assert c.post("/api/learned/forget", json={"person": "p-030", "token": "0" * 64, "approver": "p-017"}).status_code == 403
        assert c.post("/api/learned/guidelines/gl-0123456789ab", json={"action": "promote", "by": "p-017"}).status_code == 403
        assert c.post("/api/learned/gaps/kg-0123456789ab/dismiss", json={"by": "p-017"}).status_code == 403
        # an anonymous brain question that the graph cannot answer is not a knowledge gap
        a = c.post("/api/brain/ask", json={"question": "What did we decide about the quantum billing ledger?"}).json()
        assert a["knowledge_gap"] is None and c.get("/api/learned").json()["gaps"]["rows"] == []
        # a run started with the approver key is trusted: its approval is learned
        inc2, _, tok2 = _run(c, made, hdr=key)
        hdr2 = {"X-Faultline-Run-Token": tok2}
        opt2 = _flag(c, inc2, hdr2)
        spec2 = c.post(f"/api/incidents/{inc2}/choose", json={"action_id": opt2["id"]}, headers=hdr2).json()
        r2 = c.post(f"/api/incidents/{inc2}/approve", json={"action_id": opt2["id"], "plan_hash": spec2["plan_hash"],
                                                            "approver": "p-030"}, headers=hdr2)
        assert r2.status_code == 200 and r2.json()["learned"]["learned"] is True
        assert r2.json()["learned"]["family"] == "payment"
        _ = pages


def test_reject_guideline_override_then_forget_with_a_receipt(home):
    name, made = home
    with TestClient(api.app) as c:
        inc, _, _ = _run(c, made)
        opt = _flag(c, inc)
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
        rj = c.post(f"/api/incidents/{inc}/reject", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                          "approver": "p-030", "reason": "the KPI goes dark with the flag off"})
        assert rj.status_code == 200 and rj.json()["learned"]["learned"] is True
        gl = c.get("/api/learned").json()["guidelines"]["rows"]
        assert len(gl) == 1 and gl[0]["status"] == "proposed" and gl[0]["by"]["id"] == "p-030"
        gid = gl[0]["id"]
        assert c.post(f"/api/learned/guidelines/{gid}", json={"action": "promote", "by": "p-017"}).status_code == 200
        assert c.post(f"/api/learned/guidelines/{gid}", json={"action": "promote", "by": "p-017"}).status_code == 409
        inc2, _, _ = _run(c, made)
        plan = c.get(f"/api/incidents/{inc2}/plan").json()
        f2 = next(o for o in plan["options"] if o["kind"] == "flip_flag" and o["enabled"])
        assert f2["learned"]["guideline"]["needs_override"] and plan["options"][0]["kind"] == "rollback_deploy"
        assert plan["learned"]["flagged"] == [f2["id"]] and plan["learned_preferences"]["template"].startswith("Q-LEARN-PREF")
        spec2 = c.post(f"/api/incidents/{inc2}/choose", json={"action_id": f2["id"]}).json()
        body = {"action_id": f2["id"], "plan_hash": spec2["plan_hash"], "approver": "p-030"}
        no = c.post(f"/api/incidents/{inc2}/approve", json=body)
        assert no.status_code == 409 and gid in no.json()["detail"]
        bad = c.post(f"/api/incidents/{inc2}/approve", json={**body, "override_guideline": "gl-" + "f" * 16,
                                                            "override_reason": "because"})
        assert bad.status_code == 409
        ok = c.post(f"/api/incidents/{inc2}/approve", json={**body, "override_guideline": gid,
                                                           "override_reason": "an hour without the KPI is fine"})
        assert ok.status_code == 200 and ok.json()["override"]["id"] == gid
        assert _wait(c, inc2) == "RESOLVED"
        time.sleep(1.0)   # the verified hook runs at the end of the execute job
        kinds = {e["kind"] for e in c.get("/api/learned").json()["events"]["rows"]}
        assert {"reject", "approve", "override", "verified"} <= kinds
        # forget p-030: dry run → token → a stale token is refused → execute → receipt and proof
        dry = c.post("/api/learned/forget", json={"person": "p-030"}).json()
        assert dry["dry_run"] and dry["n_events"] >= 4 and gid in dry["guidelines"] and "payment" in dry["families"]
        assert c.post("/api/learned/forget", json={"person": "p-030", "token": "0" * 64, "approver": "p-017"}).status_code == 409
        assert c.post("/api/learned/forget", json={"person": "p-030", "token": dry["token"],
                                                   "approver": "nobody-here"}).status_code == 422
        ex = c.post("/api/learned/forget", json={"person": "p-030", "token": dry["token"], "approver": "p-017"})
        assert ex.status_code == 200, ex.text
        r = ex.json()
        assert r["events"] == dry["n_events"] and r["events_left"] == 0 and r["preferences_still_citing"] == 0
        assert r["proof"]["verdict"] == "forgotten"
        st = c.get("/api/learned").json()
        assert st["events"]["rows"] == [] and st["preferences"]["rows"] == [] and st["guidelines"]["rows"] == []
        assert [x for x in st["responders"]["rows"] if x["person"]["id"] == "p-030"] == []
        assert any(x["token"] == dry["token"] and x["approver"] == "p-017" for x in st["receipts"]["rows"])


def test_learned_mcp_tools_carry_their_cypher_and_respect_the_home_graph(home):
    name, _ = home
    learning.record("acme", eid="le-mcp-1", kind="ack", person="p-017", family="payment", ack_ms=60_000,
                    incident="inc-m1", page="pg-1")
    learning.record("acme", eid="le-mcp-2", kind="ack", person="p-017", family="payment", ack_ms=30_000,
                    incident="inc-m2", page="pg-2")
    tok = context.bind("acme", record=False)
    try:
        resp = T.learned_responders(target_id="payment")
        prefs = T.learned_preferences(family_id="payment")
        state = T.learned_state()
        gaps = T.knowledge_gaps()
    finally:
        context.unbind(tok)
    assert resp["template"] == "Q-LEARN-RESP" and resp["rows"][0]["person"] == "p-017" and resp["rows"][0]["acks"] == 2
    assert resp["rows"][0]["mtta_ms"] == 45_000 and name in resp["served_by"] and "MATCH" in resp["cypher"]
    assert prefs["rows"] == [] and prefs["n_family"] == 0 and "Q-LEARN-PREF" in prefs["template"]
    assert {r["kind"]: r["n"] for r in state["counts"]} == {"ack": 2}
    assert gaps["rows"] == [] and gaps["template"] == "Q-KGAP-1"
    wave = learning.first_wave({**resp, "target": "payment"})
    assert [p["person"] for p in wave] == ["p-017"] and "mean ack 45 s" in wave[0]["reason"]


def test_recall_ranks_by_similarity_and_recency(home):
    name, made = home
    db = gclient.engine()
    room = f"eval_acme_learnrecall_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", room)
    made.append(room)
    ro = RO("acme", room)
    # a seeded incident with an embedding that shares a symptom with others (test set-up read, not product logic)
    inc = db.select_graph(room).ro_query(
        "MATCH (i:Incident)-[:HAS_SYMPTOM]->(:Symptom)<-[:HAS_SYMPTOM]-(j:Incident) WHERE i.embedding IS NOT NULL "
        "AND j.id <> i.id WITH i, count(DISTINCT j) AS k ORDER BY k DESC, i.id RETURN i.id LIMIT 1").result_set[0][0]
    now = learning.now_ms()
    base = {"current": inc, "now": now, "half_life_ms": 30 * 86_400_000.0}
    sim_only = ro.run("Q-MEM-1", {**base, "w_recency": 0.0}).rows
    rec_only = ro.run("Q-MEM-1", {**base, "w_recency": 1.0}).rows
    assert sim_only and rec_only
    assert [r["distance"] for r in sim_only] == sorted(r["distance"] for r in sim_only)    # the order before M21
    assert [r["recency"] for r in rec_only] == sorted((r["recency"] for r in rec_only), reverse=True)
    tok = context.bind("acme", record=False, graph=room)
    try:
        out = T.similar_incidents(incident_id=inc, now=now)
    finally:
        context.unbind(tok)
    assert out["rows"] and all(r["line"].startswith("last seen ") for r in out["rows"])


def test_learned_endpoint_fails_loudly_under_the_a4_ablation(monkeypatch):
    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    with TestClient(api.app) as c:
        r = c.get("/api/learned")
    assert r.status_code == 503 and "FAULTLINE_DISABLE_GRAPH" in r.json()["detail"]


# ------------------------------------------------------------------ UI follow-ups (2026-10-17)
def test_template_reruns_default_to_the_templates_home_graph(home):
    """The Cypher panel's re-run read tenant_<t> for every template, so learned state (oncall_<t>) and the run index
    (audit_<t>) came back empty. Each template declares its home; `graph` picks another of the tenant's own graphs."""
    name, _ = home
    learning.record("acme", eid="le-rerun-1", kind="approve", person="p-030", family="payment", action_kind="flip_flag")
    with TestClient(api.app) as c:
        assert c.get("/api/templates/Q-LEARN-EVENTS").json()["home"] == "oncall"
        assert c.get("/api/templates/Q-RUNS-1").json()["home"] == "audit"
        assert c.get("/api/templates/Q-COUNT-1").json()["home"] == "tenant"
        r = c.post("/api/templates/Q-LEARN-EVENTS/run", json={"params": {}}).json()
        assert r["graph"] == name and [x["id"] for x in r["rows"]] == ["le-rerun-1"]
        assert c.post("/api/templates/Q-LEARN-EVENTS/run", json={"params": {}, "graph": "tenant"}).json()["rows"] == []
        runs = c.post("/api/templates/Q-RUNS-1/run", json={"params": {}}).json()
        assert runs["graph"] == "audit_acme" and runs["home"] == "audit"
        prof = c.post("/api/templates/Q-LEARN-EVENTS/profile", json={"params": {}})
        assert prof.status_code == 200 and prof.json()["graph"] == name
        assert c.post("/api/templates/Q-LEARN-EVENTS/run", json={"params": {}, "graph": "golden"}).status_code == 422
        assert c.post("/api/templates/Q-PAGE-TG/run", json={"params": {"inc": "x"}}).status_code == 403   # internal


def test_an_override_is_recorded_on_the_approval_even_when_learning_is_not(home, monkeypatch):
    """An approval past an ACTIVE guideline always records the override on the Approval and the Action (one query in
    the approve path); learning records it only for a trusted approver."""
    name, made = home
    learning.record("acme", eid=learning.event_id("reject", "test", "override"), kind="reject", person="p-030",
                    family="payment",
                    action_kind="flip_flag", reason="the KPI goes dark with the flag off")
    gid = [g for g in learning.state("acme")["guidelines"]["rows"]][0]["id"]
    assert learning.set_guideline("acme", gid, "promote", "p-017")["status"] == "active"
    monkeypatch.setattr(settings, "faultline_public", True)
    with TestClient(api.app) as c:
        inc, graph, tok = _run(c, made)
        hdr = {"X-Faultline-Run-Token": tok}
        opt = _flag(c, inc, hdr)
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}, headers=hdr).json()
        body = {"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"}
        assert c.post(f"/api/incidents/{inc}/approve", json=body, headers=hdr).status_code == 409
        ok = c.post(f"/api/incidents/{inc}/approve", json={**body, "override_guideline": gid,
                                                           "override_reason": "an hour without the KPI is fine"},
                    headers=hdr)
        assert ok.status_code == 200 and ok.json()["learned"]["learned"] is False   # an anonymous visitor's run
        act_ = next(a for a in RO("acme", graph).run("Q-ACT-1", {"inc": inc}).rows if a["id"] == opt["id"])
        assert act_["override_guideline"] == gid and act_["override_reason"] == "an hour without the KPI is fine"
        ap = gclient.engine().select_graph(graph).ro_query(
            "MATCH (ap:Approval {id: $id}) RETURN ap.override_guideline, ap.override_reason",
            {"id": act_["approval_id"]}).result_set
        assert ap == [[gid, "an hour without the KPI is fine"]]
        assert not [e for e in learning.state("acme")["events"]["rows"] if e["kind"] == "override"]


def test_plan_options_are_ordered_by_their_integer_rank(home):
    """Q-ACT-1 ordered by the id string, so act-…-10 came before act-…-2. Options now carry an integer rank."""
    name, made = home
    db = gclient.engine()
    room = f"eval_acme_rank_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", room)
    made.append(room)
    g = db.select_graph(room)
    g.query("CREATE (:Incident:Node {id: 'inc-rank-1', stage: 'AWAITING_APPROVAL'})")
    for i in range(1, 13):
        writes.record_option(g, inc="inc-rank-1", aid=f"act-inc-rank-1-{i}", kind="open_issue", option=f"option {i}",
                             enabled=True, reason="r", target="t", preview={}, rank=i)
    writes.record_option(g, inc="inc-rank-1", aid="act-inc-rank-1-h1", kind="rollback_deploy", option="human",
                         enabled=True, reason="named by a human", target="t", preview={})
    writes.record_option(g, inc="inc-rank-1", aid="act-inc-rank-1-2", kind="open_issue", option="option 2",
                         enabled=True, reason="re-recorded", target="t", preview={}, keep_future=True)   # rank kept
    ids = [a["id"] for a in RO("acme", room).run("Q-ACT-1", {"inc": "inc-rank-1"}).rows]
    assert ids == [f"act-inc-rank-1-{i}" for i in range(1, 13)] + ["act-inc-rank-1-h1"]


def test_learned_reads_never_write(home, monkeypatch):
    """GET /api/learned applied the schema on its first call per process; reads are read-only now (the API prepares
    the home graphs at startup, and a learning WRITE applies it once)."""
    name, _ = home
    from faultline.graph import writes as w

    monkeypatch.setattr(learning, "_ensured", set())
    calls = []
    real = w.apply_schema
    monkeypatch.setattr(w, "apply_schema", lambda g: (calls.append(g.name), real(g))[1])
    st = learning.state("acme")
    assert st["home"] == name and calls == []
    learning.record("acme", eid="le-ro-1", kind="ack", person="p-017", family="payment", ack_ms=1000)
    assert calls == [name]                                        # the write path ensures the schema, once
    learning.record("acme", eid="le-ro-2", kind="ack", person="p-017", family="payment", ack_ms=1000)
    assert calls == [name]
    assert learning.ensure_homes(["acme"]) == {"acme": name}


def test_status_and_the_schema_resource_list_the_engine_constraints():
    from faultline.graph import constraints as gc
    from faultline.mcp_server import resources

    with TestClient(api.app) as c:
        st = c.get("/api/status").json()
    cons = st["constraints"]
    assert cons["template"] == "Q-SCHEMA-5" and cons["declared"] == len(gc.CONSTRAINTS)
    assert cons["present"] == len(cons["rows"]) and cons["operational"] + cons["pending"] <= cons["present"]
    assert all({"type", "label", "properties", "entitytype", "status"} <= set(r) for r in cons["rows"])
    tok = context.bind("acme", record=False)
    try:
        schema = __import__("json").loads(resources.schema_resource())
    finally:
        context.unbind(tok)
    assert "constraints" in schema and any(q["template"] == "Q-SCHEMA-5" for q in schema["queries"])
