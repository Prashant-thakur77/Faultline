"""Live: the Telegram on-call bot against the graph, with the Bot API mocked (no network). Pages arrive as cards and are
edited in place; buttons and commands go through the webhook (secret header, idempotent update ids, mapped users only);
approving needs the typed phrase and passes Q-APPROVER-1 and the plan hash like the web UI; the token never appears in
a response, a recorded Bot API payload or a log line. The on-call home graph is a fresh copy of golden_acme."""

import itertools
import logging
import re
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.actions import oncall
from faultline.actions import telegram as tg
from faultline.config import settings
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
TOKEN = "FAKE-TOKEN-telegram-live-tests"
SECRET = "tg-webhook-secret-for-tests"
ON_CALL, MEMBER, VP, STRANGER = "1001", "1002", "1003", "9999"   # p-030 (payments on-call), p-017, p-001 (VP), unmapped


class FakeTelegram:
    """Records every Bot API call; answers like Telegram (message ids for sent messages)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.ids = itertools.count(500)

    def __call__(self, method: str, payload: dict) -> dict:
        self.calls.append((method, payload))
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": next(self.ids), "chat": {"id": payload["chat_id"]}}}
        return {"ok": True, "result": True}

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [p for m, p in self.calls if m == method]

    def texts(self) -> str:
        return "\n".join(p.get("text", "") for _, p in self.calls)


@pytest.fixture
def bot(monkeypatch):
    db = gclient.engine()
    home = f"eval_acme_tgtest_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", home)
    monkeypatch.setattr(oncall, "home_graph", lambda t: home)
    monkeypatch.setattr(oncall, "ASYNC", False)
    fake = FakeTelegram()
    monkeypatch.setattr(tg, "_http", fake)
    for k, v in {"telegram_bot_token": TOKEN, "telegram_webhook_secret": SECRET, "telegram_chat_id": "-500",
                 "telegram_people": f"{ON_CALL}:p-030,{MEMBER}:p-017,{VP}:p-001",
                 "faultline_public_url": "https://faultline.example"}.items():
        monkeypatch.setattr(settings, k, v)
    api._rate.clear()
    from faultline.actions import telegram_bot

    telegram_bot._hits.clear()
    made = [home]
    with TestClient(api.app) as c:
        yield c, fake, made, home
    for g in made:
        gcopy.delete_if_exists(db, g)


_uid = itertools.count(int(time.time()))


def _send(c, user, text=None, data=None, message_id=77, update_id=None):
    upd = {"update_id": update_id or next(_uid)}
    frm = {"id": int(user), "is_bot": False, "first_name": "t"}
    chat = {"id": int(user), "type": "private"}
    if data is not None:
        upd["callback_query"] = {"id": f"cb{upd['update_id']}", "from": frm, "data": data,
                                 "message": {"message_id": message_id, "chat": chat}}
    else:
        upd["message"] = {"message_id": message_id, "from": frm, "chat": chat, "text": text}
    r = c.post("/api/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert r.status_code == 200, r.text
    assert TOKEN not in r.text
    return r.json()


def _run(c, made):
    r = c.post("/api/scenarios/S1/run", json={"llm": "baseline"}).json()
    made.append(r["graph"])
    for _ in range(600):
        if c.get(f"/api/jobs/{r['job']}").json()["state"] != "running":
            break
        time.sleep(0.25)
    return r["incident"], r["graph"]


def _stage(c, inc):
    return c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]


def _wait(c, inc, stages, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = _stage(c, inc)
        if st in stages:
            return st
        time.sleep(0.3)
    raise AssertionError(st)


def _owner_page(c, inc):
    return next(p for p in c.get(f"/api/pages?incident={inc}").json()["rows"] if "failing component" in (p["reason"] or ""))


def test_webhook_auth_idempotency_and_unmapped_users(bot):
    c, fake, made, home = bot
    upd = {"update_id": 42, "message": {"message_id": 1, "from": {"id": int(ON_CALL)}, "chat": {"id": int(ON_CALL)},
                                        "text": "/help"}}
    assert c.post("/api/telegram/webhook", json=upd).status_code == 403
    assert c.post("/api/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403
    first = _send(c, ON_CALL, "/help", update_id=4242424)
    again = _send(c, ON_CALL, "/help", update_id=4242424)
    assert first.get("command") == "help" and again["ignored"] == "duplicate update"
    out = _send(c, STRANGER, "/start")
    assert out["refused"] == "unmapped user" and STRANGER in fake.sent()[-1]["text"]
    assert _send(c, STRANGER, "/pages")["refused"] == "unmapped user"
    assert TOKEN not in fake.texts()


def test_a_page_arrives_as_a_card_and_is_edited_in_place(bot, caplog):
    c, fake, made, home = bot
    with caplog.at_level(logging.DEBUG):
        _send(c, ON_CALL, "/start")                                   # p-030's pages now come to this chat
        inc, graph = _run(c, made)
        page = _owner_page(c, inc)
        cards = [p for p in fake.sent() if "caused this" in p.get("text", "")]
        mine = next(p for p in cards if str(p["chat_id"]) == ON_CALL)
        assert "D-pay-417 caused this</b>: D-pay-417 → payment → checkout" in mine["text"]
        assert "Ruled out" in mine["text"] and "(G5:" in mine["text"] and "(G2:" in mine["text"]
        assert "Why you: on call for team-payments" in mine["text"] and mine["disable_notification"] is False
        assert len(mine["text"]) <= tg.LIMIT and mine["parse_mode"] == "HTML"
        labels = [b["text"] for row in mine["reply_markup"]["inline_keyboard"] for b in row]
        assert {"✅ Acknowledge", "🔎 Why", "🛠 Options", "👥 Who fixes", "📖 Runbook", "⏭ Escalate now", "🔗 Open"} <= set(labels)
        # the Telegram mapping is internal (Q-PAGE-TG), never in the page views clients read
        assert "tg_chat" not in RO("acme", graph).run("Q-PAGE-ONE", {"page": page["id"], "now": oncall.now_ms()}).rows[0]
        row = next(r for r in RO("acme", graph).run("Q-PAGE-TG", {"inc": inc}).rows if r["id"] == page["id"])
        assert str(row["tg_chat"]) == ON_CALL and row["tg_message_id"]
        # Ack button → the same message is edited, never a new one
        before = len(fake.sent())
        out = _send(c, ON_CALL, data=f"ack:{page['id']}")
        assert out["acked"] is True
        edits = [p for p in fake.sent("editMessageText") if p["message_id"] == row["tg_message_id"]]
        assert edits and "Acknowledged by Desmond Brackwater via telegram" in edits[-1]["text"]
        assert "✅ Acknowledge" not in [b["text"] for r_ in edits[-1]["reply_markup"]["inline_keyboard"] for b in r_]
        assert len(fake.sent()) == before + 1                       # one confirmation, no second card
        ack = gclient.engine().select_graph(graph).ro_query(
            "MATCH (p:Person)-[a:ACKED]->(:Page {id: $id}) RETURN a.via, a.tg_user", {"id": page["id"]}).result_set
        assert ack == [["telegram", ON_CALL]]
        n_edits = len(fake.sent("editMessageText"))
        oncall.touch("acme", graph, inc)                             # nothing changed: no edit is sent
        assert len(fake.sent("editMessageText")) == n_edits
    assert TOKEN not in caplog.text and TOKEN not in repr(fake.calls)


def test_approving_needs_the_typed_phrase_and_the_approver_rule(bot):
    c, fake, made, home = bot
    _send(c, ON_CALL, "/start")
    inc, graph = _run(c, made)
    page = _owner_page(c, inc)
    _send(c, ON_CALL, data=f"opt:{page['id']}")
    opts = fake.sent()[-1]
    choose = next(b for row in opts["reply_markup"]["inline_keyboard"] for b in row if "paymentGate" in b["text"])
    # the VP owns nothing impacted and is not on call: refused at the choose step, with the graph's reason
    assert _send(c, VP, data=choose["callback_data"])["chosen"] is False
    assert "not on call" in fake.sent()[-1]["text"]
    out = _send(c, ON_CALL, data=choose["callback_data"])
    assert out["chosen"] is True
    offer = fake.sent()[-1]["text"]
    code = re.search(r"approve ([0-9a-f]{6})", offer).group(1)
    assert "Plan hash" in offer and "Q-APPROVER-1" in offer and "never approves" in offer
    # a tap or "yes" never approves; a wrong code finds nothing; another user cannot use this proposal
    assert _send(c, ON_CALL, "yes")["refused"] == "not the phrase"
    assert _send(c, ON_CALL, "approve")["refused"] == "not the phrase"
    assert _send(c, ON_CALL, "approve 000000")["approved"] is False
    assert _stage(c, inc) == "AWAITING_APPROVAL"
    ok = _send(c, ON_CALL, f"approve {code}")
    assert ok["approved"] is True, fake.sent()[-1]["text"]
    assert _wait(c, inc, {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED"}) == "RESOLVED"
    assert _send(c, ON_CALL, f"approve {code}")["approved"] is False           # single use
    ap = gclient.engine().select_graph(graph).ro_query(
        "MATCH (ap:Approval) RETURN ap.approver_id, ap.via, ap.tg_user").result_set
    assert ap == [["p-030", "telegram", ON_CALL]]
    time.sleep(0.5)
    card = [p for p in fake.sent("editMessageText") if "verified APPLIED" in p["text"]]
    assert card and "Resolved" in card[-1]["text"]
    # after APPLIED: grant a contract for repeats, by typed phrase, then revoke it by typed phrase
    labels = [b for row in card[-1]["reply_markup"]["inline_keyboard"] for b in row]
    grant = next(b for b in labels if "contract" in b["text"])
    assert _send(c, ON_CALL, data=grant["callback_data"])["offered"] is True
    gcode = re.search(r"grant ([0-9a-f]{6})", fake.sent()[-1]["text"]).group(1)
    assert _send(c, ON_CALL, "grant")["refused"] == "not the phrase"
    g = _send(c, ON_CALL, f"grant {gcode}")
    assert g["granted"] is True
    _send(c, ON_CALL, "/contracts")
    rcode = re.search(r"revoke ([0-9a-f]{6})", fake.sent()[-1]["text"]).group(1)
    assert _send(c, ON_CALL, f"revoke {rcode}")["revoked"] is True
    assert next(x for x in c.get("/api/contracts").json()["rows"] if x["id"] == g["contract"])["status"] == "revoked"


def test_commands_escalate_now_and_mute(bot):
    c, fake, made, home = bot
    _send(c, ON_CALL, "/start")
    inc, graph = _run(c, made)
    page = _owner_page(c, inc)
    for cmd in ("/oncall", "/pages", f"/incident {inc}", "/report", "/stats", "/help", "/nope",
                "/brain who decided the payment timeout?", "/handoff p-017 watch payment latency after the fix"):
        out = _send(c, ON_CALL, cmd)
        assert "error" not in out, (cmd, out)
        assert len(fake.sent()[-1]["text"]) <= tg.LIMIT
    texts = fake.texts()
    assert "On call now" in texts and "open page(s)" in texts and "Shift report" in texts and "MTTA" in texts
    assert "Citation guard" in texts and "Handed over to" in texts
    # Escalate now: the next person of the MSF order gets a new card; the old card says so
    out = _send(c, ON_CALL, data=f"esc:{page['id']}")
    assert out["escalated_to"]
    assert any("Escalated to" in p["text"] for p in fake.sent("editMessageText"))
    # /mute holds back information notices only
    assert _send(c, ON_CALL, "/mute 30")["muted"] == 30
    assert _send(c, ON_CALL, "/mute abc")["muted"] is False
    assert TOKEN not in fake.texts() and TOKEN not in repr(fake.calls)


def _bot_updates(home):
    return gclient.engine().select_graph(home).ro_query("MATCH (u:BotUpdate) RETURN count(u)").result_set[0][0]


def test_nothing_is_written_for_an_unmapped_user_or_a_throttled_chat(bot, monkeypatch):
    """Security review M19 #5: the mapping and the rate limit come before the update is claimed in the graph, and
    old updates and consents are pruned by the tick."""
    from faultline.actions import telegram_bot
    from faultline.agent.weights import weights
    from faultline.graph import writes

    c, fake, made, home = bot
    before = _bot_updates(home)
    assert _send(c, STRANGER, "/start")["refused"] == "unmapped user"
    assert _send(c, STRANGER, "approve abcdef")["refused"] == "unmapped user"
    assert _bot_updates(home) == before                                     # an unmapped user writes nothing
    monkeypatch.setitem(weights()["oncall"], "telegram_rate_per_min", 1)
    telegram_bot._hits.clear()
    assert "command" in _send(c, ON_CALL, "/help")
    n = _bot_updates(home)
    assert _send(c, ON_CALL, "/help")["refused"] == "rate limit"
    assert _bot_updates(home) == n                                          # a throttled update is not recorded
    g = gclient.engine().select_graph(home)
    old = oncall.now_ms() - 3 * 86_400_000
    assert writes.claim_bot_update(g, uid="tg-old-1", chat="1", user="1", kind="message", now=old)
    assert telegram_bot.prune("acme") >= 1
    assert not g.ro_query("MATCH (u:BotUpdate {id: 'tg-old-1'}) RETURN u").result_set



def test_one_wave_is_one_card_and_one_email_acks_stay_per_person_escalation_still_notifies(bot, monkeypatch):
    """The live-server report (2026-10-17): five people paged for one incident, four of them with no linked chat, gave
    five cards in the shared chat and five emails. Coalesced: one card per chat per wave, one email per wave, each Page
    still its own node recording what it was coalesced into; acknowledging stays per person; an escalation is a new
    wave and notifies again."""
    from faultline.actions import channels
    from faultline.agent.weights import weights

    c, fake, made, home = bot
    emails: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "faultline_ses_from", "pager@faultline.example")
    monkeypatch.setattr(settings, "faultline_ses_to", "owner@faultline.example")
    monkeypatch.setattr(channels, "_boto3_available", lambda: True)
    monkeypatch.setattr(channels, "_email", lambda subject, body: emails.append((subject, body)) or {"ok": True})
    monkeypatch.setitem(weights()["oncall"], "recipient_cooldown_s", 0)   # several waves within seconds, scripted
    inc, graph = _run(c, made)                                   # nobody has linked a chat: every page → the shared chat
    pages = [p for p in c.get(f"/api/pages?incident={inc}").json()["rows"] if p["kind"] == "page"]
    assert len(pages) == 5
    cards = [p for p in fake.sent() if "caused this" in p.get("text", "")]
    assert len(cards) == 1 and str(cards[0]["chat_id"]) == "-500" and "5 people paged" in cards[0]["text"]
    for p in pages:
        assert f"<b>{p['person']['name']}</b>" in cards[0]["text"]
    assert len(emails) == 1 and all(f"/oncall/page/{p['id']}" in emails[0][1] for p in pages)   # each one's own link
    # every Page is still its own node and says what it was coalesced into (the same message for all five)
    into = {p["delivery"]["telegram"]["coalesced_into"] for p in pages}
    assert len(into) == 1 and next(iter(into)).startswith("telegram message ")
    assert {p["delivery"]["email"]["coalesced_into"] for p in pages} == {f"email {oncall.wave_id(graph, inc, [x['id'] for x in pages])}"}
    assert all(p["delivery"]["telegram"]["pages"] == 5 and p["delivery"]["email"]["ok"] for p in pages)
    tg_rows = RO("acme", graph).run("Q-PAGE-TG", {"inc": inc}).rows
    assert len({(r["tg_chat"], r["tg_message_id"]) for r in tg_rows}) == 1 and len(tg_rows) == 5
    # the shared chat is nobody's: one Ack button per paged person; p-017 (mapped, not paged) acks for p-030
    labels = [b for row in cards[0]["reply_markup"]["inline_keyboard"] for b in row]
    assert len([b for b in labels if b.get("callback_data", "").startswith("ack:")]) == 5
    owner = next(p for p in pages if p["person"]["id"] == "p-030")
    sends = len(fake.sent())
    out = _send(c, MEMBER, data=f"ack:{owner['id']}")
    assert out["acked"] is True
    ack = gclient.engine().select_graph(graph).ro_query(
        "MATCH (p:Person)-[a:ACKED]->(:Page {id: $id}) RETURN p.id, a.via", {"id": owner["id"]}).result_set
    assert ack == [["p-017", "telegram"]]                       # who acted is recorded, on the paged person's page
    mid = tg_rows[0]["tg_message_id"]
    edits = [e for e in fake.sent("editMessageText") if e["message_id"] == mid]
    assert len(edits) == 1 and "Acknowledged by Quinn Lindqvane via telegram" in edits[-1]["text"]
    assert len(fake.sent()) == sends + 1                         # the confirmation only; no new card
    # a second incident: nobody acknowledges; the escalation is a new wave → one new card and one new email
    inc2, graph2 = _run(c, made)
    p2 = c.get(f"/api/pages?incident={inc2}").json()["rows"]
    cards2 = [p for p in fake.sent() if "caused this" in p.get("text", "")]
    assert len(cards2) == 2 and len(emails) == 2
    due = max(p["ack_due_at"] for p in p2)
    esc = c.post("/api/oncall/tick", json={"now": due + 1, "incident": inc2}).json()["escalated"]
    assert len(esc) == 1 and esc[0]["to"]
    cards3 = [p for p in fake.sent() if "caused this" in p.get("text", "")]
    assert len(cards3) == 3 and "ESCALATED" in cards3[-1]["text"] and len(emails) == 3
    epage = next(p for p in c.get(f"/api/pages?incident={inc2}").json()["rows"] if p["kind"] == "escalation")
    assert epage["delivery"]["telegram"]["ok"] and epage["delivery"]["telegram"]["pages"] == 1
    assert "coalesced_into" not in epage["delivery"]["telegram"]
    # the first wave's card of incident 2 is edited in place to say who it escalated to (still one card)
    w1 = {(r["tg_chat"], r["tg_message_id"]) for r in RO("acme", graph2).run("Q-PAGE-TG", {"inc": inc2}).rows
          if r["id"] != epage["id"]}
    assert len(w1) == 1
    # budget: the telegram counter took one unit per message (3 cards), not one per page (11 pages)
    n = gclient.engine().select_graph(home).ro_query(
        "MATCH (b:DeliveryBudget) WHERE b.channel = 'telegram' AND b.hour IS NOT NULL RETURN sum(b.n)").result_set[0][0]
    assert n == 3
    assert TOKEN not in fake.texts()
