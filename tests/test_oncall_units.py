"""M19 on-call units (no FalkorDB): urgency and ack windows from weights.yaml, signed page tokens, who is paged, the
channel payloads, contract parameter binding, alert parsing and the write guards."""

from __future__ import annotations

import pytest

from faultline.actions import channels, contracts, oncall
from faultline.agent.weights import weights
from faultline.config import settings
from faultline.graph import writes
from faultline.graph.templates import catalogue


def test_unknown_urgency_is_paged_as_urgent():
    assert oncall.urgency_of(True) == "urgent"
    assert oncall.urgency_of(None) == "urgent"      # an unmeasured promise is never read as safe
    assert oncall.urgency_of(False) == "normal"


def test_ack_windows_come_from_weights(monkeypatch):
    w = weights()["oncall"]
    monkeypatch.setattr(settings, "faultline_oncall_demo_windows", False)
    assert oncall.ack_window_ms("urgent") == int(w["ack_window_min"]["urgent"]) * 60_000
    assert oncall.ack_window_ms("normal") == int(w["ack_window_min"]["normal"]) * 60_000
    monkeypatch.setattr(settings, "faultline_oncall_demo_windows", True)
    assert oncall.ack_window_ms("urgent") == oncall.ack_window_ms("normal") == int(w["demo_ack_window_s"]) * 1000


def test_page_tokens_are_signed_per_page_and_tenant(monkeypatch):
    monkeypatch.setattr(settings, "faultline_page_secret", "s3cret-for-tests")
    now = 1_792_000_000_000
    tok = oncall.page_token("acme", "pg-abc123", now=now)
    assert oncall.token_ok("acme", "pg-abc123", tok, now=now)
    assert not oncall.token_ok("acme", "pg-abc124", tok, now=now)       # another page
    assert not oncall.token_ok("globex", "pg-abc123", tok, now=now)     # another tenant
    assert not oncall.token_ok("acme", "pg-abc123", None) and not oncall.token_ok("acme", "pg-abc123", "")
    monkeypatch.setattr(settings, "faultline_page_secret", "another-secret")
    assert not oncall.token_ok("acme", "pg-abc123", tok, now=now)       # a rotated key invalidates old links
    assert "&t=" in oncall.deep_link("acme", "pg-abc123")


def test_page_tokens_expire_and_the_expiry_cannot_be_edited(monkeypatch):
    """Security review M19 #11: a signed link works for weights.yaml oncall.ack_token_ttl_h, then never again."""
    monkeypatch.setattr(settings, "faultline_page_secret", "s3cret-for-tests")
    now = 1_792_000_000_000
    ttl = int(weights()["oncall"]["ack_token_ttl_h"]) * 3_600_000
    tok = oncall.page_token("acme", "pg-abc123", now=now)
    assert oncall.token_ok("acme", "pg-abc123", tok, now=now + ttl - 1)
    assert not oncall.token_ok("acme", "pg-abc123", tok, now=now + ttl + 1)
    exp, _, mac = tok.partition(".")
    later = oncall._b36(int(exp, 36) + 10 * ttl)
    assert not oncall.token_ok("acme", "pg-abc123", f"{later}.{mac}", now=now)   # a pushed-out expiry fails the MAC
    assert not oncall.token_ok("acme", "pg-abc123", "nodot", now=now)


def test_the_delivery_queue_is_bounded(monkeypatch):
    """Security review M19 #1: the background pool never takes more than oncall.delivery_queue waiting jobs."""
    import threading

    monkeypatch.setattr(oncall, "ASYNC", True)
    monkeypatch.setattr(oncall, "_queue", threading.BoundedSemaphore(1))
    assert oncall._queue.acquire(blocking=False)          # the one slot is taken (a job is waiting)
    ran = []
    assert oncall._submit(lambda: ran.append(1)) is False and ran == []
    oncall._queue.release()
    assert oncall._submit(lambda: ran.append(1)) is True


def test_ses_uses_short_timeouts_and_one_attempt(monkeypatch):
    """Security review M19 #8: Config(connect_timeout=3, read_timeout=5, retries max_attempts 1)."""
    import sys
    import types

    seen = {}

    class Config:
        def __init__(self, **kw):
            seen.update(kw)

    class Client:
        def send_email(self, **kw):
            seen["sent"] = True

    boto3 = types.SimpleNamespace(client=lambda name, config=None, **kw: (seen.setdefault("config", config), Client())[1])
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", types.ModuleType("botocore"))
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=Config))
    monkeypatch.setattr(settings, "faultline_ses_from", "pager@example.org")
    monkeypatch.setattr(settings, "faultline_ses_to", "oncall@example.org")
    assert channels._email("s", "b") == {"ok": True}
    assert seen["connect_timeout"] == 3 and seen["read_timeout"] == 5 and seen["retries"] == {"max_attempts": 1}


def test_page_ids_are_deterministic_per_step():
    a = oncall.page_id("g", "inc", "p-1", "page", 1)
    assert a == oncall.page_id("g", "inc", "p-1", "page", 1) and a.startswith("pg-")
    assert a != oncall.page_id("g", "inc", "p-1", "escalation", 2) != oncall.page_id("g", "inc", "p-2", "page", 1)


def test_recipients_owner_on_call_first_then_blast_radius_teams_once_each():
    who = {"oncall_now": ["p-030"], "owner_team": "team-payments", "evidence_id": "ev_who"}
    notify = {"evidence_id": "ev_n", "rows": [
        {"team": "team-checkout", "name": "Checkout", "owns_impacted": ["checkout"], "oncall": ["p-005"]},
        {"team": "team-payments", "name": "Payments", "owns_impacted": ["x"], "oncall": ["p-030"]},
        {"team": "team-data", "name": "Data", "owns_impacted": ["kpi"], "oncall": []}]}
    out = oncall.recipients(who, notify, "payment")
    assert [r["person"] for r in out] == ["p-030", "p-005"]
    assert "failing component" in out[0]["reason"] and out[0]["evidence"] == "ev_who"
    assert oncall.recipients(None, None, "x") == []


def test_slack_payload_button_only_with_a_link_and_style_only_on_pages():
    p = channels.slack_payload("page", "t", "x", incident="inc-1", link="https://f.example/oncall/page/pg-1")
    btn = next(b for b in p["blocks"] if b["type"] == "actions")["elements"][0]
    assert btn["url"].endswith("pg-1") and btn["style"] == "primary"
    n = channels.slack_payload("contract_notice", "t", "x", incident=None, link="https://f.example/x")
    assert "style" not in next(b for b in n["blocks"] if b["type"] == "actions")["elements"][0]
    assert not any(b["type"] == "actions" for b in channels.slack_payload("page", "t", "x", incident=None, link="")["blocks"])


def test_pagerduty_triggers_pages_resolves_and_never_wakes_for_a_notice():
    pd = channels.pagerduty_payload("page", "t", "x", tenant="acme", incident="inc-1", link="", routing_key="k")
    assert pd["event_action"] == "trigger" and pd["dedup_key"] == "faultline:acme:inc-1"
    assert channels.pagerduty_payload("resolved", "t", "x", tenant="acme", incident="inc-1", link="",
                                      routing_key="k")["event_action"] == "resolve"
    assert channels.pagerduty_payload("contract_notice", "t", "x", tenant="acme", incident="inc-1", link="",
                                      routing_key="k") is None


def test_telegram_ack_button_only_on_pages_and_fits_callback_limit():
    t = channels.telegram_payload("page", "t", "x", page_id="pg-0123456789abcd", link="https://f/x", chat_id="1")
    row = t["reply_markup"]["inline_keyboard"][0]
    ack = next(b for b in row if b.get("callback_data"))
    assert ack["callback_data"] == "ack:pg-0123456789abcd" and len(ack["callback_data"]) <= 64
    n = channels.telegram_payload("contract_notice", "t", "x", page_id="pg-1", link="/relative", chat_id="1")
    assert "reply_markup" not in n   # no ack for a notice, no relative URL button


def test_send_with_nothing_configured_is_in_app_only(monkeypatch):
    for k in ("faultline_webhook_url", "telegram_bot_token", "telegram_chat_id", "pagerduty_routing_key",
              "faultline_ses_from", "faultline_ses_to"):
        monkeypatch.setattr(settings, k, "")
    assert channels.external() == []
    assert channels.send("page", "t", "x", tenant="acme", incident="i", page_id="pg-1", link="") == {"in_app": {"ok": True}}


def test_a_failing_webhook_is_recorded_never_raised(monkeypatch):
    monkeypatch.setattr(settings, "faultline_webhook_url", "http://127.0.0.1:9/hook")  # nothing listens on port 9
    res = channels.send("page", "t", "x", tenant="acme", incident="i", page_id="pg-1", link="")
    assert res["in_app"]["ok"] and res["webhook"]["ok"] is False and "error" in res["webhook"]


def test_ses_is_an_optional_import(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_boto(name, *a, **k):
        if name == "boto3":
            raise ImportError("no boto3")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_boto)
    assert channels._email("s", "b") == {"ok": False, "error": "boto3 not installed"}


def test_secrets_never_appear_in_the_channel_status(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:SECRETTOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(settings, "pagerduty_routing_key", "PDKEYSECRET")
    text = repr(channels.configured())
    assert "SECRETTOKEN" not in text and "PDKEYSECRET" not in text


def test_contract_params_bind_the_change_not_the_reviewers():
    a = {"repo": "o/r", "path": "flags.json", "flag": "paymentGate", "state": "off", "reviewers": ["p-1"]}
    b = {**a, "reviewers": ["p-2", "p-3"]}
    h = contracts.params_hash("flip_flag", contracts.action_params("flip_flag", a))
    assert h == contracts.params_hash("flip_flag", contracts.action_params("flip_flag", b))
    assert h != contracts.params_hash("flip_flag", contracts.action_params("flip_flag", {**a, "flag": "otherFlag"}))
    assert h != contracts.params_hash("flip_flag", contracts.action_params("flip_flag", {**a, "state": "on"}))
    with pytest.raises(contracts.ContractRefused):
        contracts.action_params("open_issue", {"repo": "o/r"})
    with pytest.raises(contracts.ContractRefused):
        contracts.action_params("data_repair", {})


def test_no_contract_applies_without_a_gate_confirmed_family():
    opts = [{"id": "a1", "enabled": True, "kind": "flip_flag", "option": "flag x → off",
             "args": {"repo": "o/r", "path": "f", "flag": "x", "state": "off"}}]
    m = contracts.match_plan(tenant="acme", home="tenant_acme", family=None, options=opts)
    assert m["match"] is None and "confirmed no cause" in m["why"] and m["queries"] == []


def test_alertmanager_and_generic_payloads():
    from faultline.api import _parse_alerts

    am = {"version": "4", "status": "firing", "alerts": [
        {"status": "firing", "labels": {"alertname": "HighErrorRate", "service": "checkout", "severity": "critical"},
         "annotations": {"summary": "checkout 5xx"}, "startsAt": "2026-10-17T10:00:00Z"},
        {"status": "resolved", "labels": {"service": "payment"}},
        {"status": "firing", "labels": {"service": "bad id with spaces"}}]}
    out = _parse_alerts(am)
    assert [(a["target"], a["metric"], a["severity"]) for a in out] == [("checkout", "higherrorrate", "critical")]
    assert out[0]["at"] == 1792231200000 and out[0]["summary"] == "checkout 5xx"
    g = _parse_alerts({"service": "payment", "metric": "error_rate", "severity": "page", "summary": "x"})
    assert g == [{"target": "payment", "metric": "error_rate", "severity": "page", "summary": "x", "at": None}]
    assert _parse_alerts({"nothing": 1}) == []


def test_write_guards_refuse_bad_values():
    with pytest.raises(writes.WriteError):
        writes.create_pages(None, tenant="acme", inc="i", pages=[{"id": "pg-1", "person": "p", "kind": "nap",
                                                                   "urgency": "urgent", "window_ms": 1}], now=0)
    with pytest.raises(writes.WriteError):
        writes.contract_use_verdict(None, uid="cu-1", verdict="FINE", now=0)
    with pytest.raises(writes.WriteError):
        writes.settle_pages(None, inc="i", status="acked", detail="", now=0)
    with pytest.raises(writes.WriteError):
        writes.create_note_page(None, tenant="acme", pid="pg-1", person="p", kind="page", detail="", reason="", now=0)


def test_on_call_templates_are_in_the_linted_catalogue():
    cat = catalogue()
    for tid in ("Q-APPROVER-1", "Q-PERSON-1", "Q-ONCALL-NOW", "Q-PAGES", "Q-PAGE-OPEN", "Q-PAGE-ONE", "Q-PAGE-CHAIN",
                "Q-PAGE-OVERDUE", "Q-PAGE-NEXT", "Q-CONTRACT-MATCH", "Q-CONTRACTS", "Q-CONTRACT-OFFER", "Q-SHIFT-REPORT",
                "Q-ONCALL-STATS", "Q-HANDOFF-FROM"):
        assert tid in cat
    # the approver template reads ON_CALL now (the M19 bug: it claimed "on call" and never read the rota)
    assert "ON_CALL" in cat["Q-APPROVER-1"].text and "eligible" in cat["Q-APPROVER-1"].text
    # the contract match and the guarded use carry the same conditions
    for cond in ("c.uses < c.max_uses", "c.expires_at > $now", "c.status = 'active'", "p.active"):
        assert cond in cat["Q-CONTRACT-MATCH"].text and cond in writes.W_CONTRACT_USE


def test_on_call_mcp_tools_are_read_only_and_hosted():
    from faultline.agent.phases import INTERNAL_TOOLS
    from faultline.mcp_server import tools as T
    from faultline.mcp_server.titles import TITLES

    for name in ("oncall_now", "pages", "oncall_stats"):
        assert name in T.TOOLS and name not in INTERNAL_TOOLS and TITLES.get(name)


def test_no_write_query_name_is_defined_twice():
    """A second `W_X = …` silently replaces the first for every function that uses it (M19 shadowed the task
    hand-off query this way until the live concurrency test caught it)."""
    import re
    from pathlib import Path

    src = Path(writes.__file__).read_text()
    names = re.findall(r"^(W_[A-Z0-9_]+) = ", src, re.M)
    assert sorted({n for n in names if names.count(n) > 1}) == []


def test_internal_templates_are_never_run_for_a_client():
    """Security review M19 #4: Telegram ids, consents and contract offers are read by the product only."""
    from fastapi import HTTPException

    from faultline.api import _runnable

    internal = {k for k, t in catalogue().items() if t.internal}
    assert {"Q-BOT-CHAT", "Q-BOT-CHATS", "Q-BOT-PROPOSAL", "Q-CONTRACT-OFFER", "Q-PAGE-TG", "Q-PAGE-GRAPHS"} <= internal
    for tid in internal:
        with pytest.raises(HTTPException) as e:
            _runnable(tid)
        assert e.value.status_code == 403
    assert _runnable("Q-PAGES").id == "Q-PAGES"
    # no client-visible template returns a Telegram column (the MCP pages tool reads Q-PAGES)
    for tid, t in catalogue().items():
        if not t.internal:
            assert "tg_" not in t.text, tid


def test_the_text2cypher_guard_refuses_the_bot_state():
    from faultline.graph import guard as G

    for q in ("MATCH (c:BotChat) RETURN c.id", "MATCH (p:BotProposal) RETURN p.id", "MATCH (u:BotUpdate) RETURN u.id",
              "MATCH (p:Page) RETURN p.tg_chat", "MATCH (n) RETURN n.chat", "MATCH (a:Approval) RETURN a.tg_user"):
        with pytest.raises(G.GuardError):
            G.guard(q)


def test_send_skips_every_channel_it_is_told_to(monkeypatch):
    """A channel refused by the budget is never posted to (security review M19 #1)."""
    posts = []
    monkeypatch.setattr(channels, "_post", lambda url, payload, headers=None: (posts.append(url), {"ok": True})[1])
    monkeypatch.setattr(settings, "faultline_webhook_url", "https://hooks.example/x")
    monkeypatch.setattr(settings, "pagerduty_routing_key", "pd-key")
    out = channels.send("page", "t", "x", tenant="acme", incident="i", page_id="pg-1", link="", skip=("webhook", "pagerduty"))
    assert posts == [] and set(out) == {"in_app"}
    out = channels.send("page", "t", "x", tenant="acme", incident="i", page_id="pg-1", link="")
    assert len(posts) == 2 and {"webhook", "pagerduty"} <= set(out)



def test_a_page_link_is_stable_for_its_page(monkeypatch):
    """The card's link carries a token whose expiry comes from the page's sent_at, so re-rendering an unchanged card
    gives the same text (no needless Telegram edits)."""
    monkeypatch.setattr(settings, "faultline_page_secret", "s3cret-for-tests")
    a = oncall.deep_link("acme", "pg-0011", issued_at=1_792_000_000_000)
    assert a == oncall.deep_link("acme", "pg-0011", issued_at=1_792_000_000_000)
    assert oncall.token_ok("acme", "pg-0011", a.split("&t=")[1], now=1_792_000_000_000 + 3_600_000)
