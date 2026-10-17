"""Live: the security review of M19, one test per finding. External channels are mocked (no network); every incident
runs in a clean room; the on-call graph is a fresh copy of golden_acme unless a test says otherwise."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.actions import channels, contracts, oncall
from faultline.actions import github as gh
from faultline.agent.weights import weights
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
KEY = "k" * 32


@pytest.fixture
def room(monkeypatch):
    db = gclient.engine()
    home = f"eval_acme_oncallsec_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", home)
    monkeypatch.setattr(oncall, "home_graph", lambda t: home)
    monkeypatch.setattr(oncall, "ASYNC", False)
    posts: list[tuple[str, dict]] = []
    monkeypatch.setattr(channels, "_post", lambda url, payload, headers=None: (posts.append((url, payload)), {"ok": True})[1])
    monkeypatch.setattr(settings, "faultline_webhook_url", "https://hooks.example/abc")
    monkeypatch.setattr(settings, "faultline_approver_key", KEY)
    api._rate.clear()
    made = [home]
    yield home, made, posts
    for g in made:
        gcopy.delete_if_exists(db, g)


def _run(c, made, headers=None, sid="S1"):
    r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"}, headers=headers or {}).json()
    made.append(r["graph"])
    for _ in range(600):
        if c.get(f"/api/jobs/{r['job']}").json()["state"] != "running":
            break
        time.sleep(0.25)
    return r["incident"], r["graph"], r.get("run_token")


def _wait(c, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(st)


def _pages(graph, inc):
    return RO("acme", graph).run("Q-PAGES", {"incident": inc, "statuses": [], "now": oncall.now_ms()}).rows


def _grant_from_applied(c, made, hdr=None):
    """A trusted S1 run, approved by the payments on-call, then a contract for repeats."""
    inc, graph, _ = _run(c, made, headers=hdr)
    opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["kind"] == "flip_flag" and o["enabled"])
    spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}, headers=hdr or {}).json()
    assert c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                          "approver": "p-030"}, headers=hdr or {}).status_code == 200
    assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
    ch = c.post(f"/api/incidents/{inc}/contract", json={"step": "choose", "scope": {"max_uses": 3, "days": 1}},
                headers=hdr or {}).json()
    g = c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"], "approver": "p-030"},
               headers={**(hdr or {}), "X-Faultline-Approver-Key": KEY})
    assert g.status_code == 200, g.text
    return g.json()["contract"]["id"]


# ------------------------------------------------------------------ HIGH 1: anonymous runs page in-app only; a budget
def test_an_anonymous_public_run_pages_in_app_only(room, monkeypatch):
    home, made, posts = room
    monkeypatch.setattr(settings, "faultline_public", True)
    with TestClient(api.app) as c:
        inc, graph, token = _run(c, made)
        rows = _pages(graph, inc)
        assert rows and posts == []                                  # nothing left the building
        assert all("in-app only" in str(r["delivery"]) for r in rows)
        flag = gclient.engine().select_graph(graph).ro_query("MATCH (i:Incident {id: $i}) RETURN i.page_external",
                                                             {"i": inc}).result_set
        assert flag == [[False]]
        # the same scenario started with the approver key is trusted: its pages go out (within the budget)
        inc2, graph2, _ = _run(c, made, headers={"X-Faultline-Approver-Key": KEY})
        assert posts and all("in-app only" not in str(r["delivery"]) for r in _pages(graph2, inc2))


def test_the_hourly_budget_and_the_recipient_cooldown_hold_pages_in_app(room, monkeypatch):
    """Since coalescing (2026-10-17), the budget and the cooldown count MESSAGES: one wave (the five pages of one
    incident) is one webhook post and one unit of the hourly budget; a message is held back by the cooldown only when
    every person it is for was buzzed on that channel within oncall.recipient_cooldown_s."""
    import json

    home, made, posts = room
    monkeypatch.setitem(weights()["oncall"]["delivery_per_hour"], "webhook", 1)
    monkeypatch.setitem(weights()["oncall"], "recipient_cooldown_s", 0)
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        rows = _pages(graph, inc)
        d = [json.loads(r["delivery"]) for r in rows]
        assert len(rows) == 5 and len(posts) == 1                       # one message for the wave
        assert all(x["webhook"]["ok"] and x["webhook"]["pages"] == 5 for x in d)
        assert len({x["webhook"]["coalesced_into"] for x in d}) == 1
        inc2, graph2, _ = _run(c, made)                                  # the hour's one message is spent
        rows2 = _pages(graph2, inc2)
        assert len(posts) == 1 and rows2
        assert all("budget: webhook sent its 1 messages this hour" in str(r["delivery"]) for r in rows2)
        assert all(r["status"] == "delivery_failed" for r in rows2)     # still in the in-app pager, still escalating
        # the cooldown: everyone the next wave is for was buzzed on the webhook seconds ago → held back
        monkeypatch.setitem(weights()["oncall"], "recipient_cooldown_s", 20)
        monkeypatch.setitem(weights()["oncall"]["delivery_per_hour"], "webhook", 60)
        inc3, graph3, _ = _run(c, made)
        rows3 = _pages(graph3, inc3)
        assert len(posts) == 1 and all("paged on webhook less than 20 s ago" in str(r["delivery"]) for r in rows3)
    g = gclient.engine().select_graph(home)
    now = oncall.now_ms()
    assert writes.take_recipient_cooldown(g, channel="webhook", recipient="p-x", cooldown_ms=20_000, now=now)
    assert not writes.take_recipient_cooldown(g, channel="webhook", recipient="p-x", cooldown_ms=20_000, now=now + 1000)
    assert writes.take_recipient_cooldown(g, channel="webhook", recipient="p-x", cooldown_ms=20_000, now=now + 21_000)


# ------------------------------------------------------------------ HIGH 2: re-arm never touches on-call state
def test_rearm_keeps_the_on_call_graph(monkeypatch):
    db = gclient.engine()
    home = oncall.home_graph("acme")
    assert home == "oncall_acme" != "tenant_acme"
    g = db.select_graph(home)
    cid = f"ct-{uuid.uuid4().hex[:16]}"
    now = oncall.now_ms()
    writes.offer_contract(g, cid=cid, tenant="acme", family="payment", kind="flip_flag", params_hash="x", params={},
                          max_uses=1, days=1, expires_at=now + 86_400_000, now=now, ttl_ms=60_000, hash_=cid * 2, inc="i",
                          graph=home, aid="a", covers="payment", quote="rearm test")
    try:
        assert writes.grant_contract(g, cid=cid, hash_=cid * 2, by="p-030", covers="payment", now=now)
        gcopy.rearm(db, "acme", reason="security-test")
        assert any(r["id"] == cid for r in contracts.listing("acme", home)["rows"])
    finally:
        g.query("MATCH (c:Contract {id: $id}) DETACH DELETE c", {"id": cid})


# ------------------------------------------------------------------ MEDIUM 3: real-GitHub authority; trusted runs only
def test_contracts_need_real_github_authority_and_a_trusted_run(room, monkeypatch):
    home, made, posts = room
    with TestClient(api.app) as c:
        cid = _grant_from_applied(c, made)        # simulated GitHub: granted without real-GitHub authority
        ct = RO("acme", home).run("Q-CONTRACT-MATCH", {"family": "payment", "kind": "flip_flag",
                                                       "params_hash": contracts.listing("acme", home)["rows"][0]["params_hash"],
                                                       "now": oncall.now_ms()}).rows[0]
        assert ct["id"] == cid and ct["real_ok"] is False
        # Telegram may not grant against real GitHub without TELEGRAM_APPROVE_REAL
        monkeypatch.setattr(gh, "is_real", lambda: True)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            api.bot_contract_grant("acme", "inc-x", "0" * 64, "p-030")
        assert e.value.status_code == 403
        # with real GitHub, a contract granted without that authority never acts: a human is paged instead
        inc, graph, _ = _run(c, made)
        assert _wait(c, inc, {"AWAITING_APPROVAL", "RESOLVED"}) == "AWAITING_APPROVAL"
        assert any(r["kind"] == "page" and "without the authority real GitHub needs" in (r["detail"] or "")
                   for r in _pages(graph, inc))
        assert next(x for x in contracts.listing("acme", home)["rows"] if x["id"] == cid)["uses"] == 0
        monkeypatch.setattr(gh, "is_real", lambda: False)
        # an anonymous public run never considers a contract, even one that matches exactly
        monkeypatch.setattr(settings, "faultline_public", True)
        inc3, graph3, _ = _run(c, made)
        assert not any(r["kind"] == "contract_notice" for r in _pages(graph3, inc3))
        assert next(x for x in contracts.listing("acme", home)["rows"] if x["id"] == cid)["uses"] == 0


# ------------------------------------------------------------------ MEDIUM 6: nobody paged after a crash
def test_a_contract_that_never_settles_pages_its_people(room, monkeypatch):
    home, made, posts = room
    with TestClient(api.app) as c:
        _grant_from_applied(c, made)
        monkeypatch.setattr(api, "_contract_job", lambda *a, **k: {"acted": False})   # the process "crashes" here
        inc, graph, _ = _run(c, made)
        notices = [r for r in _pages(graph, inc) if r["kind"] == "contract_notice"]
        assert notices and all(r["ack_due_at"] > r["sent_at"] for r in notices)   # a notice carries a deadline
        due = max(r["ack_due_at"] for r in notices)
        out = c.post("/api/oncall/tick", json={"now": due + 1, "incident": inc}).json()["escalated"]
        assert out and all(x["why"] == "contract deadline" for x in out)
        pages = [r for r in _pages(graph, inc) if r["kind"] == "page"]
        assert {r["person"] for r in pages} == {n["person"] for n in notices}
        assert all(r["urgency"] == "urgent" and "no verified APPLIED fix followed" in r["detail"] for r in pages)
        assert all(r["status"] == "superseded" for r in _pages(graph, inc) if r["kind"] == "contract_notice")
        assert c.post("/api/oncall/tick", json={"now": due + 2, "incident": inc}).json()["escalated"] == []


# ------------------------------------------------------------------ LOW 7: a durable index of graphs holding pages
def test_escalation_reads_a_durable_index_of_page_graphs(room):
    home, made, posts = room
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        idx = [r["graph"] for r in RO("acme", home).run("Q-PAGE-GRAPHS", {"after": ""}).rows]
        assert graph in idx and graph in oncall.tenant_graphs("acme")
        gcopy.delete_if_exists(gclient.engine(), graph)
        assert graph not in oncall.tenant_graphs("acme")
        assert graph not in [r["graph"] for r in RO("acme", home).run("Q-PAGE-GRAPHS", {"after": ""}).rows]


# ------------------------------------------------------------------ LOW 9: rate limits on the readers, a keyed tick
def test_on_call_readers_are_rate_limited(room, monkeypatch):
    home, made, posts = room
    with TestClient(api.app) as c:
        now = time.time()
        for key, path in (("pages", "/api/pages"), ("oncall-report", "/api/oncall/report"),
                          ("oncall-stats", "/api/oncall/stats")):
            api._rate[f"{key}:testclient"] = [now] * 60
            assert c.get(path).status_code == 429, path
        api._rate.clear()
        monkeypatch.setattr(settings, "faultline_public", True)
        assert c.post("/api/oncall/tick", json={}).status_code == 403
        assert c.post("/api/oncall/tick", json={}, headers={"X-Faultline-Approver-Key": KEY}).status_code == 200


# ------------------------------------------------------------------ LOW 10: a retry never uses a contract twice
def test_a_retried_use_counts_once_and_an_unexecuted_use_is_given_back(room):
    home, made, posts = room
    g = gclient.engine().select_graph(home)
    now = oncall.now_ms()
    writes.offer_contract(g, cid="ct-feedfeedfeedfeed", tenant="acme", family="payment", kind="flip_flag", params_hash="ph",
                          params={}, max_uses=1, days=1, expires_at=now + 86_400_000, now=now - 1000, ttl_ms=60_000,
                          hash_="f" * 64, inc="i", graph=home, aid="a", covers="payment", quote="")
    assert writes.grant_contract(g, cid="ct-feedfeedfeedfeed", hash_="f" * 64, by="p-030", covers="payment", now=now - 500)
    m = {"id": "ct-feedfeedfeedfeed", "family": "payment", "kind": "flip_flag", "params_hash": "ph"}
    first = contracts.use(home=home, match=m, inc="inc-1", graph=home, aid="act-1", now=now)
    again = contracts.use(home=home, match=m, inc="inc-1", graph=home, aid="act-1", now=now)   # the same use, retried
    assert first["fresh"] is True and again["fresh"] is False and again["uses"] == 1 and again["use"] == first["use"]
    assert contracts.use(home=home, match=m, inc="inc-2", graph=home, aid="act-2", now=now) is None   # exhausted
    back = contracts.give_back(home=home, uid=first["use"])
    assert back == {"uses": 0, "status": "active"}
    assert contracts.give_back(home=home, uid=first["use"]) is None                                  # once only
