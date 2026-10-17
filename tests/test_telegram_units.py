"""Telegram on-call bot units (no FalkorDB, no network): HTML escaping and Telegram's 4096-character limit, the page
card in each state, callback sizes, the typed-phrase consent rule, the TELEGRAM_PEOPLE mapping, the per-chat rate
limit, the digest hour, and the bot token never appearing in a log line or a result."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.request

import pytest

from faultline.actions import telegram as tg
from faultline.actions import telegram_bot as bot
from faultline.config import settings

TOKEN = "FAKE-TOKEN-for-tests-not-a-real-bot"


def _view(**over) -> dict:
    page = {"id": "pg-0123456789abcd", "kind": "page", "urgency": "urgent", "status": "sent", "person": "p-030",
            "person_name": "Desmond Brackwater", "reason": "on call for team-payments, which owns payment (the failing component)",
            "detail": "The gate confirmed D-pay-417 (on payment) as the cause.", "ack_due_at": 1792239300000,
            "acked_by": None, "escalated_to": None}
    page.update(over.pop("page", {}))
    v = {"incident": "inc-s1-abcd", "title": "Checkout errors <script>alert(1)</script>", "stage": "AWAITING_APPROVAL",
         "cause": "D-pay-417", "chain": ["D-pay-417", "payment", "checkout"],
         "ruled_out": [{"cause": "D-email-88", "gate": "G5", "short": "cannot carry the impact", "reason": "G5: max flow"},
                       {"cause": "D-rec-12", "gate": "G2", "short": "no causal path", "reason": "G2: no path"}],
         "obligations": {"breach": {"slo": "checkout-availability", "breach_in_min": 42.4}, "customers_reached": 3,
                         "revenue_at_risk": 12000.0},
         "acted": {}, "incident_url": "https://faultline.example/incidents/inc-s1-abcd?tenant=acme",
         "phone_url": "https://faultline.example/oncall/page/pg-0123456789abcd?tenant=acme&t=tok", "page": page}
    v.update(over)
    return v


def _buttons(kb: dict) -> list[dict]:
    return [b for row in kb["inline_keyboard"] for b in row]


def test_escape_and_links_are_safe():
    assert tg.esc("<b>&\"x\"</b>") == "&lt;b&gt;&amp;\"x\"&lt;/b&gt;"
    assert tg.link("javascript:alert(1)", "x") == "" and tg.link("", "x") == ""
    assert tg.link('https://a.example/?q="><b>', "go") == '<a href="https://a.example/?q=&quot;&gt;&lt;b&gt;">go</a>'


def test_fit_never_exceeds_the_limit_and_never_cuts_an_entity():
    lines = ["a" * 100] * 100 + ["&amp;" * 2000]
    text = tg.fit(lines)
    assert len(text) <= tg.SAFE < tg.LIMIT and text.endswith("(trimmed: open the incident for the rest)")
    one = tg.fit(["x" * 10 + "&amp;" * 2000])
    assert len(one) <= tg.SAFE and not one.rstrip("…").endswith(("&", "&a", "&am", "&amp"))


def test_split_keeps_every_line_within_the_limit():
    lines = [f"line {k} " + "z" * 300 for k in range(60)]
    chunks = tg.split(lines)
    assert len(chunks) > 1 and all(len(c) <= tg.SAFE for c in chunks)
    assert "\n".join(chunks).split("\n") == lines


def test_the_page_card_says_what_a_phone_needs():
    text, kb = tg.page_card(_view())
    assert len(text) <= tg.LIMIT
    assert "🔴 URGENT" in text and "<b>D-pay-417 caused this</b>: D-pay-417 → payment → checkout" in text
    assert "D-email-88 (G5: cannot carry the impact)" in text and "D-rec-12 (G2: no causal path)" in text
    assert "checkout-availability breaches in ~42 min" in text and "3 customer(s), 12,000 MRR at risk" in text
    assert "Why you: on call for team-payments" in text and "Ack by" in text and "or it escalates" in text
    assert "Phone page</a>" in text and "Incident room</a>" in text
    assert "<script>" not in text and "&lt;script&gt;" in text          # the title is escaped
    labels = [b["text"] for b in _buttons(kb)]
    for want in ("✅ Acknowledge", "⏭ Escalate now", "🔎 Why", "🛠 Options", "👥 Who fixes", "📖 Runbook", "🔗 Open"):
        assert want in labels
    assert all(len(b["callback_data"].encode()) <= 64 for b in _buttons(kb) if "callback_data" in b)


def test_the_card_follows_the_incident():
    acked, kb = tg.page_card(_view(page={"status": "acked", "acked_by": "p-004", "acked_by_name": "Dorian Marrowby",
                                         "ack_via": "telegram", "acked_at": 1792239000000}))
    assert "Acknowledged by Dorian Marrowby via telegram" in acked
    assert "✅ Acknowledge" not in [b["text"] for b in _buttons(kb)]
    esc_, _ = tg.page_card(_view(page={"status": "escalated", "escalated_to": "pg-1", "escalated_at": 1792239000000},
                                 escalated_to_name="Dorian Marrowby"))
    assert "Escalated to Dorian Marrowby" in esc_
    done = {"option": "flag paymentGate → off", "verdict": "APPLIED", "kind": "flip_flag", "approver": "p-030",
            "approver_name": "Desmond Brackwater", "external_ref": "https://github.com/o/r/pull/7"}
    res, kb = tg.page_card(_view(stage="RESOLVED", acted=done, page={"status": "resolved"}))
    assert "Resolved</b>: flag paymentGate → off verified APPLIED" in res and 'href="https://github.com/o/r/pull/7"' in res
    assert "🌙 Grant a contract for repeats" in [b["text"] for b in _buttons(kb)]
    slept, kb = tg.page_card(_view(stage="RESOLVED", acted={**done, "approver": "contract:ct-0011223344556677"},
                                   page={"kind": "contract_notice", "urgency": "urgent", "status": "resolved"}))
    assert "HANDLED UNDER CONTRACT" in slept and "Fixed while you slept" in slept and "ct-0011223344556677" in slept
    assert "🌙 Grant a contract for repeats" not in [b["text"] for b in _buttons(kb)]
    no_cause, _ = tg.page_card(_view(cause=None, chain=[], stage="UNKNOWN_ESCALATED"))
    assert "No cause confirmed by the gate" in no_cause


def test_a_huge_card_still_fits_one_message():
    v = _view(title="T" * 5000, ruled_out=[{"cause": "D-" + "x" * 900, "gate": "G2", "short": "no causal path",
                                             "reason": ""}] * 4, page={"reason": "r" * 5000, "detail": "d" * 5000})
    text, _ = tg.page_card(v)
    assert len(text) <= tg.SAFE


def test_callback_data_over_64_bytes_is_refused():
    with pytest.raises(ValueError):
        tg.cb("why", "x" * 70)


def test_only_the_exact_phrase_is_consent():
    for ok in ("approve 3fa9c2", "Approve 3FA9C2.", "  grant abcdef ", "revoke 0011ab"):
        assert bot.PHRASE.match(ok)
    for bad in ("approve", "approve it", "approve 3fa9c", "approve 3fa9c2x", "yes approve 3fa9c2", "approve: 3fa9c2"):
        assert not bot.PHRASE.match(bad)
    for refused in ("yes", "OK", "ok.", "approve", "approve it please", "👍", "go ahead", "grant"):
        assert bot.consent_refusal(refused), refused
    assert bot.consent_refusal("what broke?") is None


def test_people_mapping(monkeypatch, caplog):
    monkeypatch.setattr(settings, "telegram_people", "1001:p-030, 1002:p-017,bad,:p-1,abc:p-2,1003:P BAD,-100200:p-004")
    with caplog.at_level(logging.WARNING, logger="faultline.telegram"):
        m = bot.people_map()
    assert m == {"1001": "p-030", "1002": "p-017", "-100200": "p-004"}
    assert "malformed" in caplog.text


def test_rate_limit_per_chat():
    cap = int(bot.weights()["oncall"]["telegram_rate_per_min"])
    assert all(bot.rate_ok("chat-a", now=1000.0 + k * 0.01) for k in range(cap))
    assert not bot.rate_ok("chat-a", now=1001.0)
    assert bot.rate_ok("chat-b", now=1001.0)                    # another chat is not affected
    assert bot.rate_ok("chat-a", now=1100.0)                    # a minute later it is allowed again


def test_digest_hour(monkeypatch):
    monkeypatch.setattr(settings, "telegram_digest_hour", 7)
    assert bot.digest_due(1792220400000)        # 2026-10-15T07:00Z
    assert not bot.digest_due(1792224000000)    # 08:00Z
    monkeypatch.setattr(settings, "telegram_digest_hour", -1)
    assert not bot.digest_due(1792220400000)


def test_the_bot_token_never_reaches_a_log_or_a_result(monkeypatch, caplog):
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)

    def unreachable(req, timeout=None):
        raise urllib.error.URLError(f"cannot reach {req.full_url}")
    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with caplog.at_level(logging.DEBUG):
        out = tg.call("sendMessage", {"chat_id": 1, "text": "x"})
    assert out["ok"] is False and TOKEN not in repr(out) and TOKEN not in caplog.text

    def rejected(req, timeout=None):  # Telegram's own error, echoing the URL in the message and the body
        raise urllib.error.HTTPError(req.full_url, 401, f"Unauthorized {req.full_url}", None,
                                     io.BytesIO(f'{{"ok":false,"description":"Unauthorized for {TOKEN}"}}'.encode()))
    monkeypatch.setattr(urllib.request, "urlopen", rejected)
    with caplog.at_level(logging.DEBUG):
        out = tg.call("getMe", {})
    assert out["ok"] is False and out["error_code"] == 401 and TOKEN not in repr(out) and TOKEN not in caplog.text
    assert "<token>" in out["description"]
    from faultline.actions import channels

    monkeypatch.setattr(settings, "telegram_chat_id", "-100")
    assert TOKEN not in repr(channels.configured())
    assert TOKEN not in repr(channels.send("page", "t", "x", tenant="acme", incident="i", page_id="pg-1", link=""))
    assert TOKEN not in caplog.text


def test_no_command_or_description_carries_anything_secret():
    assert len(tg.COMMANDS) >= 12 and all(len(d) <= 256 for _, d in tg.COMMANDS)
    assert len(tg.DESCRIPTION) <= 512 and len(tg.SHORT_DESCRIPTION) <= 120 and "No path, no claim" in tg.SHORT_DESCRIPTION


def test_the_test_token_is_obviously_fake():
    """Security review M19 #12: never a value shaped like a real bot token (<digits>:<35 characters>)."""
    import re

    assert not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", TOKEN) and TOKEN.startswith("FAKE")


def test_the_exact_action_and_runbook_lines_escape_once():
    """Security review M19 #13: no double escape, every value escaped."""
    line = bot.change_line({"kind": "open_issue", "title": "Incident <x> & co"})
    assert "Incident &lt;x&gt; &amp; co" in line and "&amp;amp;" not in line and "&amp;lt;" not in line
    assert bot.change_line({"kind": "flip_flag", "args": {"flag": "a<b", "state": "off"}}).endswith("flags.a&lt;b.state → off")
    rb = bot.runbook_line({"title": "T", "id": "rb-1", "source": "derived", "support": "<b>3</b>", "steps": ["a & b"]})
    assert "support &lt;b&gt;3&lt;/b&gt;" in rb and "a &amp; b" in rb



# ------------------------------------------------------------------ coalesced delivery: one card per chat per wave
def _wave(chat_person=None, statuses=("sent", "sent", "sent", "sent", "sent")) -> dict:
    people = [("p-030", "Desmond Brackwater", "on call for team-payments, which owns payment (the failing component)"),
              ("p-005", "Bram Okafor", "on call for Checkout, which owns checkout in the blast radius of payment"),
              ("p-015", "Ines Tal", "on call for Data, which owns raw.raw_orders in the blast radius of payment"),
              ("p-023", "Ola Ren", "on call for Assistant, which owns mcp in the blast radius of payment"),
              ("p-028", "Kai Mori", "on call for Storefront, which owns frontend in the blast radius of payment")]
    pages = [{"id": f"pg-00000000000{k}aa", "kind": "page", "urgency": "urgent", "status": st, "person": pid,
              "person_name": name, "reason": why, "detail": "The gate confirmed D-pay-417.", "ack_due_at": 1792239300000}
             for k, ((pid, name, why), st) in enumerate(zip(people, statuses))]
    v = _view()
    v.update(pages=pages, page=pages[0], chat_person=chat_person, phone_url="",
             phone_urls={q["id"]: f"https://faultline.example/oncall/page/{q['id']}?tenant=acme&t=tok" for q in pages})
    return v


def test_a_wave_in_one_chat_is_one_card_listing_everyone_paged():
    text, kb = tg.page_card(_wave())
    assert len(text) <= tg.LIMIT and "5 people paged" in text and "👥 Paged (5):" in text
    for name in ("Desmond Brackwater", "Bram Okafor", "Ines Tal", "Ola Ren", "Kai Mori"):
        assert f"<b>{name}</b>" in text
    assert text.count("page</a>") == 5 and "Why you" not in text      # each person's own signed page link
    # a shared chat nobody in the wave is linked to: one Ack button per paged person (who tapped is recorded)
    acks = [b for b in _buttons(kb) if b.get("callback_data", "").startswith("ack:")]
    assert len(acks) == 5 and {b["callback_data"] for b in acks} == {f"ack:pg-00000000000{k}aa" for k in range(5)}
    assert "⏭ Escalate now" in [b["text"] for b in _buttons(kb)]
    assert all(len(b["callback_data"].encode()) <= 64 for b in _buttons(kb) if "callback_data" in b)


def test_the_chats_own_person_gets_one_ack_that_acts_for_them():
    _, kb = tg.page_card(_wave(chat_person="p-015"))
    acks = [b for b in _buttons(kb) if b.get("callback_data", "").startswith("ack:")]
    assert [(b["text"], b["callback_data"]) for b in acks] == [("✅ Acknowledge", "ack:pg-000000000002aa")]


def test_a_wave_card_follows_the_ack_and_drops_the_ack_buttons():
    v = _wave(statuses=("superseded", "acked", "superseded", "superseded", "superseded"))
    v["pages"][1].update(acked_by="p-005", acked_by_name="Bram Okafor", ack_via="telegram", acked_at=1792239000000)
    v["page"] = v["pages"][1]
    text, kb = tg.page_card(v)
    assert "Acknowledged by Bram Okafor via telegram" in text and "Bram Okafor</b> (<code>p-005</code>)" in text
    assert "✅ acknowledged" in text
    assert not [b for b in _buttons(kb) if b.get("callback_data", "").startswith("ack:")]
