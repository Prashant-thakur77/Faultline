"""Live (M19 on-call): pages, escalation, acks, the approver rule, standing contracts and their negative cases, the
shift report and stats, public-mode rules, the A4 ablation, Telegram acks and alert intake, over HTTP on clean rooms.
The on-call home graph (contracts, hand-offs, alert incidents) is a fresh copy of golden_acme per test, so the live
tenant graph is never written."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.actions import contracts, oncall
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.fixture
def home(monkeypatch):
    db = gclient.engine()
    name = f"eval_acme_oncalltest_{uuid.uuid4().hex[:8]}"
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


def _stage(c, inc):
    return c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]


def _wait(c, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = _stage(c, inc)
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(f"{inc} stuck at {st}")


def _pages(c, inc):
    return c.get(f"/api/pages?incident={inc}").json()["rows"]


def _approve_flag(c, inc, approver):
    opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["kind"] == "flip_flag" and o["enabled"])
    spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
    return c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                         "approver": approver}), opt, spec


def test_q_approver_reads_on_call_and_ownership():
    """The M19 bug fix: Q-APPROVER-1 reads ON_CALL. On call for the owner team (and a member), a member of the owner
    team, and someone who neither owns nor is on call for the impacted components (refused, with a reason)."""
    ro = RO("acme")
    now = oncall.now_ms()
    p = {"ids": ["payment", "checkout"], "since": now - 3_600_000, "now": now}
    on = ro.run("Q-APPROVER-1", {**p, "person": "p-030"}).rows[0]
    member = ro.run("Q-APPROVER-1", {**p, "person": "p-017"}).rows[0]
    vp = ro.run("Q-APPROVER-1", {**p, "person": "p-001"}).rows[0]
    assert on["eligible"] and ["team-payments", "payment"] in on["oncall_owns"]
    assert member["eligible"] and not member["oncall_owns"] and member["member_owns"]
    assert vp["eligible"] is False
    assert ro.run("Q-APPROVER-1", {**p, "person": "nobody-here"}).rows == []
    # a component nobody in the person's teams owns: not eligible even though they are on call
    assert ro.run("Q-APPROVER-1", {**p, "ids": ["recommendation"], "person": "p-030"}).rows[0]["eligible"] is False


def test_page_escalate_ack_approve_then_the_same_fault_runs_under_contract(home):
    name, made = home
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        assert _stage(c, inc) == "AWAITING_APPROVAL"
        pages = _pages(c, inc)
        assert pages and all(p["kind"] == "page" and p["status"] == "sent" and p["urgency"] in ("urgent", "normal")
                             for p in pages)
        owner = next(p for p in pages if "failing component" in (p["reason"] or ""))
        onset = c.get(f"/api/incidents/{inc}").json()["incident"]["onset_at"]
        rota = {r["team"]: r["person"] for r in RO("acme", graph).run("Q-ONCALL-NOW", {"now": onset}).rows}
        assert owner["person"]["id"] == rota["team-payments"] and owner["ack_token"]   # the failing component's on-call
        detail = c.get(f"/api/pages/{owner['id']}").json()
        assert detail["incident"]["cause"] and detail["proof"]["nodes"][0] == detail["incident"]["cause"]
        assert detail["chain"]["template"] == "Q-PAGE-CHAIN" and detail["who_fixes"]["rows"]
        # nobody acks in time: one escalation to the next person of the MSF order, every overdue page links to it
        due = max(p["ack_due_at"] for p in pages)
        assert c.post("/api/oncall/tick", json={"now": due - 1, "incident": inc}).json()["escalated"] == []
        tick = c.post("/api/oncall/tick", json={"now": due + 1, "incident": inc}).json()["escalated"]
        assert len(tick) == 1 and tick[0]["incident"] == inc and tick[0]["to"]
        after = _pages(c, inc)
        esc = next(p for p in after if p["kind"] == "escalation")
        assert esc["person"]["id"] == tick[0]["to"] and esc["attempt"] == 2
        assert all(p["status"] == "escalated" and p["escalated_to"] == esc["id"] for p in after if p["kind"] == "page")
        # acks: a wrong token is refused, the page's own token acknowledges, twice is a 409, escalation stops
        assert c.post(f"/api/pages/{esc['id']}/ack", json={"token": "forged"}).status_code == 403
        ok = c.post(f"/api/pages/{esc['id']}/ack", json={"token": esc["ack_token"]})
        assert ok.status_code == 200 and ok.json()["via"] == "token"
        assert c.post(f"/api/pages/{esc['id']}/ack", json={"token": esc["ack_token"]}).status_code == 409
        assert c.post("/api/oncall/tick", json={"now": due + 10 ** 8, "incident": inc}).json()["escalated"] == []
        # the approver rule: the VP owns nothing impacted and is not on call → 403 with the graph's reason
        bad, _, _ = _approve_flag(c, inc, "p-001")
        assert bad.status_code == 403 and "not on call" in bad.json()["detail"]
        ok, opt, _ = _approve_flag(c, inc, owner["person"]["id"])
        assert ok.status_code == 200 and ok.json()["approver"]["eligible"] and ok.json()["approver"]["reason"]
        assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
        # grant a contract (two steps, hash-bound, single use)
        ch = c.post(f"/api/incidents/{inc}/contract", json={"step": "choose", "scope": {"max_uses": 1, "days": 7}}).json()
        assert ch["scope"]["family"] and ch["scope"]["action_kind"] == "flip_flag"
        assert c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": "0" * 64,
                                                              "approver": owner["person"]["id"]}).status_code == 409
        assert c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"],
                                                              "approver": "p-001"}).status_code == 403
        gr = c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"],
                                                            "approver": owner["person"]["id"]})
        assert gr.status_code == 200 and gr.json()["contract"]["status"] == "active"
        assert c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"],
                                                              "approver": owner["person"]["id"]}).status_code == 409
        # the same fault again: handled under the contract, nobody paged, verified, the use recorded
        inc2, graph2, _ = _run(c, made)
        assert _wait(c, inc2, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
        p2 = _pages(c, inc2)
        assert p2 and {p["kind"] for p in p2} == {"contract_notice"}
        acted = next(o for o in c.get(f"/api/incidents/{inc2}/plan").json()["options"] if o["verdict"])
        assert acted["verdict"] == "APPLIED"
        ct = next(x for x in c.get("/api/contracts").json()["rows"] if x["id"] == gr.json()["contract"]["id"])
        assert ct["uses"] == 1 and ct["status"] == "exhausted" and ct["used_in"][0]["verdict"] == "APPLIED"
        # exhausted: the third time pages humans again
        inc3, _, _ = _run(c, made)
        assert _stage(c, inc3) == "AWAITING_APPROVAL" and {p["kind"] for p in _pages(c, inc3)} == {"page"}
        st = c.get("/api/oncall/stats?days=1").json()
        assert st["handled_under_contract"] >= 1 and st["people_paged"] >= 1 and st["mtta_ms"] is not None
        rep = c.get("/api/oncall/report").json()
        assert rep["counts"]["contract_uses"] >= 1 and rep["counts"]["acks"] >= 1 and rep["summary"]


def test_a_contract_never_fires_when_revoked_expired_or_for_other_params(home):
    name, made = home
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        ok, _, _ = _approve_flag(c, inc, "p-030")
        assert ok.status_code == 200
        # approving is acknowledging: the approver's page is acked via approval, the others superseded
        after = {p["person"]["id"]: p for p in _pages(c, inc)}
        assert after["p-030"]["status"] == "acked" and after["p-030"]["ack"]["via"] == "approval"
        assert all(p["status"] == "superseded" for pid, p in after.items() if pid != "p-030")
        assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
        # revoked
        ch = c.post(f"/api/incidents/{inc}/contract", json={"step": "choose", "scope": {"max_uses": 3, "days": 7}}).json()
        cid = c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"],
                                                             "approver": "p-030"}).json()["contract"]["id"]
        assert c.post(f"/api/contracts/{cid}/revoke", json={"by": "p-030"}).json()["revoked"]
        assert c.post(f"/api/contracts/{cid}/revoke", json={}).status_code == 409
        # expired: granted 8 days ago for 7 days (the clock shifted for the grant)
        past = oncall.now_ms() - 8 * 86_400_000
        old = contracts.offer(tenant="acme", graph=graph, inc=inc, home=name, max_uses=3, days=7, now=past)
        assert contracts.grant(tenant="acme", home=name, hash_=old["hash"], by="p-030", now=past)["status"] == "active"
        # other params: the same family and kind, a different flag
        g = gclient.engine().select_graph(name)
        now = oncall.now_ms()
        other = contracts.params_hash("flip_flag", {**ch["scope"]["params"], "flag": "someOtherFlag"})
        writes.offer_contract(g, cid="ct-" + "e" * 16, tenant="acme", family=ch["scope"]["family"], kind="flip_flag",
                              params_hash=other, params={}, max_uses=3, days=7, expires_at=now + 86_400_000, now=now,
                              ttl_ms=60_000, hash_="e" * 64, inc=inc, graph=graph, aid="x", covers=ch["scope"]["family"], quote="")
        assert writes.grant_contract(g, cid="ct-" + "e" * 16, hash_="e" * 64, by="p-030", covers="", now=now)
        rows = {x["id"]: x["status"] for x in c.get("/api/contracts").json()["rows"]}
        assert rows[cid] == "revoked" and rows[old["contract_id"]] == "expired" and rows["ct-" + "e" * 16] == "active"
        inc2, _, _ = _run(c, made)
        assert _stage(c, inc2) == "AWAITING_APPROVAL"
        assert {p["kind"] for p in _pages(c, inc2)} == {"page"}
        assert all(x["uses"] == 0 for x in c.get("/api/contracts").json()["rows"])


def test_the_guarded_use_refuses_exhausted_expired_revoked_and_changed(home):
    """W_CONTRACT_USE alone (the single write that authorises acting without a human): every refusal case."""
    name, _ = home
    g = gclient.engine().select_graph(name)
    now = oncall.now_ms()

    def grant(cid, max_uses=1, expires=now + 86_400_000):
        writes.offer_contract(g, cid=cid, tenant="acme", family="payment", kind="flip_flag", params_hash="ph", params={},
                              max_uses=max_uses, days=1, expires_at=expires, now=now - 1000, ttl_ms=60_000, hash_=cid * 2,
                              inc="i", graph=name, aid="a", covers="payment", quote="")
        assert writes.grant_contract(g, cid=cid, hash_=cid * 2, by="p-030", covers="payment", now=now - 500)
    m = {"family": "payment", "kind": "flip_flag", "params_hash": "ph"}
    grant("ct-aaaaaaaaaaaaaaaa")
    assert contracts.use(home=name, match={**m, "id": "ct-aaaaaaaaaaaaaaaa"}, inc="i1", graph=name, aid="a", now=now)
    assert contracts.use(home=name, match={**m, "id": "ct-aaaaaaaaaaaaaaaa"}, inc="i2", graph=name, aid="a", now=now) is None
    grant("ct-bbbbbbbbbbbbbbbb", max_uses=5, expires=now + 1000)
    assert contracts.use(home=name, match={**m, "id": "ct-bbbbbbbbbbbbbbbb"}, inc="i", graph=name, aid="a",
                         now=now + 2000) is None   # expired
    grant("ct-cccccccccccccccc", max_uses=5)
    assert contracts.revoke(home=name, cid="ct-cccccccccccccccc", by="p-030")
    assert contracts.use(home=name, match={**m, "id": "ct-cccccccccccccccc"}, inc="i", graph=name, aid="a", now=now) is None
    grant("ct-dddddddddddddddd", max_uses=5)
    assert contracts.use(home=name, match={**m, "id": "ct-dddddddddddddddd", "params_hash": "other"}, inc="i", graph=name,
                         aid="a", now=now) is None   # different params
    assert contracts.use(home=name, match={**m, "id": "ct-dddddddddddddddd", "family": "cart"}, inc="i", graph=name,
                         aid="a", now=now) is None   # different family
    match = RO("acme", name).run("Q-CONTRACT-MATCH", {"family": "payment", "kind": "flip_flag", "params_hash": "ph",
                                                       "now": now + 2000}).rows
    assert [r["id"] for r in match] == ["ct-dddddddddddddddd"]   # exhausted, expired and revoked never match


def test_an_abstaining_gate_pages_a_human_and_never_considers_a_contract(home):
    """S12: no change explains it; the origin is inferred, NOT confirmed. Humans are paged; the plan's on-call record says
    no contract applies because the gate confirmed no cause (even with a contract present for that component)."""
    name, made = home
    now = oncall.now_ms()
    g = gclient.engine().select_graph(name)
    for fam in ("currency", "checkout"):
        writes.offer_contract(g, cid=f"ct-{fam[:4]}000000000000", tenant="acme", family=fam, kind="flip_flag", params_hash="x",
                              params={}, max_uses=5, days=1, expires_at=now + 86_400_000, now=now, ttl_ms=60_000,
                              hash_=f"{fam}h", inc="i", graph=name, aid="a", covers=fam, quote="")
        writes.grant_contract(g, cid=f"ct-{fam[:4]}000000000000", hash_=f"{fam}h", by="p-030", covers=fam, now=now)
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made, "S12")
        pages = _pages(c, inc)
        assert pages and {p["kind"] for p in pages} == {"page"}
        assert all(x["uses"] == 0 for x in c.get("/api/contracts").json()["rows"])


def test_public_mode_rules(home, monkeypatch):
    name, made = home
    monkeypatch.setattr(settings, "faultline_public", True)
    monkeypatch.setattr(settings, "faultline_approver_key", "k" * 32)
    with TestClient(api.app) as c:
        inc, graph, token = _run(c, made)
        pages = _pages(c, inc)
        assert pages and all("ack_token" not in p for p in pages)   # never handed out in a list on the public demo
        pid = pages[0]["id"]
        assert c.post(f"/api/pages/{pid}/ack", json={}).status_code == 403
        key = {"X-Faultline-Approver-Key": "k" * 32}
        assert c.post("/api/oncall/tick", json={}).status_code == 403                       # on-demand tick: keyed only
        assert c.post("/api/oncall/tick", json={"now": 1, "incident": inc}, headers=key).status_code == 403  # no clock
        assert c.post("/api/oncall/tick", json={"incident": inc}, headers=key).status_code == 200
        ok = c.post(f"/api/pages/{pid}/ack", json={}, headers={"X-Faultline-Run-Token": token})
        # the run-token holder is who acted: recorded as such, never as the paged person, and left out of MTTA
        assert ok.status_code == 200 and ok.json()["via"] == "run_token" and ok.json()["by"]["id"] is None
        acked = next(p for p in _pages(c, inc) if p["id"] == pid)
        assert acked["ack"]["by"] is None and acked["ack"]["actor"] == "run-token holder"
        assert oncall.stats("acme", since=0, graphs=[graph])["acked_incidents"] == 0
        hdr = {"X-Faultline-Run-Token": token}
        opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"] if o["kind"] == "flip_flag" and o["enabled"])
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}, headers=hdr).json()
        assert c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                              "approver": "p-030"}, headers=hdr).status_code == 200
        assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
        ch = c.post(f"/api/incidents/{inc}/contract", json={"step": "choose", "scope": {"max_uses": 1, "days": 1}},
                    headers=hdr).json()
        body = {"step": "approve", "hash": ch["hash"], "approver": "p-030"}
        assert c.post(f"/api/incidents/{inc}/contract", json=body).status_code == 403            # no run token
        assert c.post(f"/api/incidents/{inc}/contract", json=body, headers=hdr).status_code == 403  # no approver key
        ok = c.post(f"/api/incidents/{inc}/contract", json=body, headers={**hdr, "X-Faultline-Approver-Key": "k" * 32})
        assert ok.status_code == 200
        cid = ok.json()["contract"]["id"]
        assert c.post(f"/api/contracts/{cid}/revoke", json={}).status_code == 403
        assert c.post(f"/api/contracts/{cid}/revoke", json={}, headers={"X-Faultline-Approver-Key": "k" * 32}).status_code == 200
        assert c.post("/api/handoffs", json={"note": "n", "to": "p-017"}).status_code == 403
        assert c.post("/api/alerts", json={"service": "checkout"}).status_code == 401


def test_handoff_report_and_now(home):
    name, _ = home
    with TestClient(api.app) as c:
        now = c.get("/api/oncall/now").json()
        assert now["template"] == "Q-ONCALL-NOW" and any(r["person"] for r in now["rows"])
        assert c.post("/api/handoffs", json={"note": "watch payment", "to": "nobody-here"}).status_code == 422
        h = c.post("/api/handoffs", json={"note": "watch payment latency", "to": "p-017", "from": "p-030"})
        assert h.status_code == 200 and h.json()["handoff"]["id"].startswith("ho-")
        rep = c.get("/api/oncall/report").json()
        assert any(x["id"] == h.json()["handoff"]["id"] for x in rep["handoffs"])
        report_pages = [p for p in c.get("/api/pages").json()["rows"] if p["kind"] == "report"]
        assert report_pages and report_pages[0]["person"]["id"] == "p-017"


def test_telegram_ack_button(home, monkeypatch):
    """The Ack button through the webhook: only a user mapped to a person (TELEGRAM_PEOPLE) acknowledges, recorded
    via telegram (the full bot: tests/live/test_telegram_live.py)."""
    from faultline.actions import telegram as tg

    name, made = home
    monkeypatch.setattr(settings, "telegram_webhook_secret", "tg-secret")
    monkeypatch.setattr(settings, "telegram_people", "4242:p-030")
    monkeypatch.setattr(tg, "_http", lambda method, payload: {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(settings, "telegram_bot_token", "1:test-token")
    with TestClient(api.app) as c:
        inc, _, _ = _run(c, made)
        pid = _pages(c, inc)[0]["id"]
        upd = {"update_id": 900001, "callback_query": {"id": "1", "data": f"ack:{pid}", "from": {"id": 4242},
                                                       "message": {"message_id": 5, "chat": {"id": 4242}}}}
        assert c.post("/api/telegram/webhook", json=upd).status_code == 403
        assert c.post("/api/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
        stranger = {"update_id": 900002, "callback_query": {"id": "2", "data": f"ack:{pid}", "from": {"id": 1},
                                                            "message": {"message_id": 5, "chat": {"id": 1}}}}
        assert c.post("/api/telegram/webhook", json=stranger,
                      headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"}).json()["refused"] == "unmapped user"
        r = c.post("/api/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"}).json()
        assert r["acked"] is True
        assert next(p for p in _pages(c, inc) if p["id"] == pid)["ack"]["via"] == "telegram"


def test_alert_intake_opens_an_incident_and_pages_a_human(home):
    """A real alert (no scenario, nothing simulated): INTAKE opens an incident in the on-call home graph and the run
    loop investigates it; with no telemetry to prove a cause it escalates, and a human is paged."""
    name, _ = home
    with TestClient(api.app) as c:
        r = c.post("/api/alerts", json={"version": "4", "alerts": [
            {"status": "firing", "labels": {"service": "checkout", "alertname": "error_rate", "severity": "critical"},
             "annotations": {"summary": "checkout 5xx above 5%"}}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["graph"] == name and body["incident"].startswith("inc-alert-")
        for _ in range(300):
            j = c.get(f"/api/jobs/{body['job']}").json()
            if j["state"] != "running":
                break
            time.sleep(0.3)
        assert j["state"] == "done", j
        assert j["incidents"][0]["outcome"] in ("UNKNOWN_ESCALATED", "NOT_CONFIDENT", "NO_INCIDENT", "CONFIRMED")
        if j["incidents"][0]["outcome"] != "NO_INCIDENT":
            assert _pages(c, body["incident"])
        assert c.post("/api/alerts", json={"service": "not-a-component"}).status_code == 422
        assert c.post("/api/alerts", json={"nothing": 1}).status_code == 422


def test_a4_on_call_routes_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    with TestClient(api.app) as c:
        for path in ("/api/oncall/now", "/api/pages", "/api/contracts", "/api/oncall/stats", "/api/oncall/report",
                     "/api/pages/pg-0123456789abcd"):
            assert c.get(path).status_code == 503, path
        assert c.post("/api/oncall/tick", json={}).status_code == 503
        assert c.post("/api/pages/pg-0123456789abcd/ack", json={"token": "x"}).status_code == 503


def test_a_contract_run_that_does_not_verify_pages_a_human_at_once(home, monkeypatch):
    """Under a contract the action runs without paging, but verification still runs: when it cannot confirm the fix
    (here the second channel is made unreadable → UNKNOWN), a human is paged at once (urgent), the informational
    notices are superseded and the contract's use records the verdict."""
    from faultline.actions import act
    from faultline.graph import writes as W

    name, made = home
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        ok, _, _ = _approve_flag(c, inc, "p-030")
        assert ok.status_code == 200
        assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "RESOLVED"
        ch = c.post(f"/api/incidents/{inc}/contract", json={"step": "choose", "scope": {"max_uses": 2, "days": 1}}).json()
        cid = c.post(f"/api/incidents/{inc}/contract", json={"step": "approve", "hash": ch["hash"],
                                                             "approver": "p-030"}).json()["contract"]["id"]

        def unreadable(cx, aid, hub, **kw):  # the second channel cannot be read: UNKNOWN, never success
            why = "test: GitHub main could not be read; escalated to a human"
            W.record_verdict(cx.g(), aid=aid, verdict="UNKNOWN", why=why, channels={"github_main": {"ok": None}},
                             owner=cx.owner)
            return {"verdict": "UNKNOWN", "explanation": why, "channels": {}}
        monkeypatch.setattr(act, "verify", unreadable)
        inc2, _, _ = _run(c, made)
        assert _wait(c, inc2, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"}) == "UNKNOWN_ESCALATED"
        p2 = _pages(c, inc2)
        humans = [p for p in p2 if p["kind"] == "page"]
        assert humans and all(p["urgency"] == "urgent" and p["status"] == "sent" for p in humans)
        assert all(p["detail"].startswith(f"Verification UNKNOWN after approval by standing contract {cid}:") for p in humans)
        assert all(p["status"] == "superseded" for p in p2 if p["kind"] == "contract_notice")
        ct = next(x for x in c.get("/api/contracts").json()["rows"] if x["id"] == cid)
        assert ct["uses"] == 1 and ct["used_in"][0]["verdict"] == "UNKNOWN"
        assert c.get("/api/oncall/stats?days=1").json()["handled_under_contract"] == 0   # not RESOLVED: not "handled"


def _verify_as(verdict: str):
    """A stand-in for act.verify that records `verdict` (the second channel said so) and returns it."""
    from faultline.graph import writes as W

    def fake(cx, aid, hub, **kw):
        why = f"test: the second channel says {verdict}"
        W.record_verdict(cx.g(), aid=aid, verdict=verdict, why=why, channels={"test": {"ok": None}}, owner=cx.owner)
        return {"verdict": verdict, "explanation": why, "channels": {}}
    return fake


def test_a_human_approved_fix_that_ends_unknown_pages_a_human_once(home, monkeypatch):
    """The human path: an approved fix whose verification is UNKNOWN ends UNKNOWN_ESCALATED and pages, urgently, the
    people already paged about the incident and the approver. The reconciler settling the same outcome later pages
    nobody twice; the new wave still escalates when nobody acknowledges it (an earlier ack does not silence it)."""
    from faultline.actions import act
    from faultline.actions import github as gh
    from faultline.actions import reconcile

    name, made = home
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        before = {p["id"] for p in _pages(c, inc)}
        monkeypatch.setattr(act, "verify", _verify_as("UNKNOWN"))
        ok, _, _ = _approve_flag(c, inc, "p-017")   # a payments member who was not paged
        assert ok.status_code == 200
        assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED"}) == "UNKNOWN_ESCALATED"
        after = [p for p in _pages(c, inc) if p["id"] not in before]
        assert after and all(p["kind"] == "page" and p["urgency"] == "urgent" and p["status"] == "sent" for p in after)
        assert all(p["detail"].startswith("Verification UNKNOWN after approval by p-017:") for p in after)
        people = {p["person"]["id"] for p in after}
        assert "p-017" in people and "p-030" in people          # the approver and the on-call paged before
        # the reconciler settles the same intent to the same outcome: no second page
        loc = api._locate(inc, "acme")
        cx = act.Ctx("acme", graph, inc, loc["run"])
        out = reconcile.reconcile("acme", graph, gh.client(graph), lambda i: api._world(cx, loc), older_than_ms=0,
                                  oncall_home=name)
        assert out and out[0]["verdict"] == "UNKNOWN"
        assert {p["id"] for p in _pages(c, inc) if p["id"] not in before} == {p["id"] for p in after}
        # nobody acknowledges the new wave: it escalates (the approver's earlier ack-by-approval does not count)
        due = max(p["ack_due_at"] for p in after)
        tick = c.post("/api/oncall/tick", json={"now": due + 1, "incident": inc}).json()["escalated"]
        assert [t["incident"] for t in tick] == [inc] and tick[0]["to"]


def test_a_human_approved_fix_that_does_not_apply_pages_a_human(home, monkeypatch):
    from faultline.actions import act

    name, made = home
    with TestClient(api.app) as c:
        inc, graph, _ = _run(c, made)
        before = {p["id"] for p in _pages(c, inc)}
        monkeypatch.setattr(act, "verify", _verify_as("NOT_APPLIED"))
        ok, _, _ = _approve_flag(c, inc, "p-030")
        assert ok.status_code == 200
        t0 = time.time()
        while time.time() - t0 < 60 and not [p for p in _pages(c, inc) if p["id"] not in before]:
            time.sleep(0.3)
        assert _stage(c, inc) == "AWAITING_APPROVAL"            # back to a human: the option is disabled
        after = [p for p in _pages(c, inc) if p["id"] not in before]
        assert after and all(p["urgency"] == "urgent" and "did NOT apply (NOT_APPLIED)" in p["detail"] for p in after)
