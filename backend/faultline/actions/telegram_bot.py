"""Telegram on-call bot, the inbound half: one update → one answer: an allowlist, buttons that never approve on their
own, consent only by an exact typed phrase.

Safety, in the order a webhook call meets it:
1. the API checked the webhook secret (constant time) before this module runs;
2. every update is processed once: its update_id is claimed in the on-call home graph (W_BOT_UPDATE, one MERGE);
3. a per-chat rate limit (weights.yaml oncall.telegram_rate_per_min);
4. only a Telegram user the operator mapped to a person (TELEGRAM_PEOPLE "tg_user_id:p-030,…") may do anything but
   /start; the person must be active in the graph;
5. acknowledging is open to any mapped person; choosing and approving go through the SAME code as the web UI
   (api.bot_choose / api.bot_approve: Q-APPROVER-1, the plan hash, the intent lease), recorded `via: telegram` with
   the Telegram user id;
6. a button never approves: "Choose N" renders the exact action and its plan hash and opens a single-use proposal
   (W_BOT_PROPOSAL, TTL weights.yaml oncall.contract_offer_ttl_s); only the typed reply `approve <first 6 of the
   hash>` from the same user in the same chat approves it (W_BOT_PROPOSAL_USE, one guarded write). "yes", "ok" or a
   bare "approve" are refused with the reason. Granting a standing contract (`grant <6>`) and revoking one
   (`revoke <6>`) are typed phrases too.
Every read is a catalogue template; every write a single query in graph/writes.py. Nothing here logs the bot token.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Any

from ..agent.weights import weights
from ..config import settings
from ..graph import client as gclient
from ..graph import writes
from ..graph.errors import GraphError
from ..graph.ro import RO
from ..graph.tenant import check_tenant
from . import contracts, oncall
from . import telegram as tg
from .telegram import clip, esc, hhmm

log = logging.getLogger("faultline.telegram")

PHRASE = re.compile(r"^\s*(approve|grant|revoke)\s+([0-9a-f]{6})\s*[.!]?\s*$", re.I)
BARE_CONSENT = {"yes", "y", "ok", "okay", "sure", "go", "go ahead", "do it", "approve", "approved", "grant", "confirm",
                "lgtm", "yes please", "👍", "✅", "ship it"}
PERSON_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,40}$")
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()

HELP = [
    "<b>Faultline on-call bot</b>: no path, no claim.",
    "/oncall who is on call now · /pages open pages · /incident &lt;id&gt; status card · /ack &lt;page&gt;",
    "/brain &lt;question&gt; ask the company brain · /report shift report · /handoff &lt;person&gt; &lt;note&gt;",
    "/contracts standing approvals · /stats MTTA, MTTR · /mute &lt;minutes&gt; silence notices (pages still ring)",
    "",
    "<b>Approving from here</b>: tap 🛠 Options, then Choose N. I show the exact action and its plan hash; reply with "
    "the exact phrase <code>approve &lt;first 6 of the hash&gt;</code> within the time shown. A tap, \"yes\" or \"ok\" "
    "never approves. You must be on call for, or own, a component the incident impacts (the same rule as the web UI).",
]


def people_map() -> dict[str, str]:
    """TELEGRAM_PEOPLE "tg_user_id:p-030,…" → {"tg_user_id": "p-030"}; malformed entries are ignored (and logged)."""
    out: dict[str, str] = {}
    for part in (settings.telegram_people or "").split(","):
        part = part.strip()
        if not part:
            continue
        uid, _, person = part.partition(":")
        uid, person = uid.strip(), person.strip()
        if uid.lstrip("-").isdigit() and PERSON_RE.match(person):
            out[uid] = person
        else:
            log.warning("TELEGRAM_PEOPLE: ignoring a malformed entry")
    return out


def rate_ok(chat: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    cap = int(weights()["oncall"]["telegram_rate_per_min"])
    with _hits_lock:
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 120]:
                _hits.pop(k, None)
        recent = [x for x in _hits.get(chat, []) if now - x < 60]
        ok = len(recent) < cap
        if ok:
            recent.append(now)
        _hits[chat] = recent
    return ok


def consent_refusal(text: str) -> str | None:
    """Why a typed message is NOT consent, when it looks like an attempt to approve (None otherwise)."""
    t = " ".join(text.lower().split()).strip(" .!")
    if t in BARE_CONSENT or re.match(r"^(approve|grant|revoke)\b", t):
        return ("That is not the approval phrase. Reply with exactly <code>approve &lt;first 6 of the plan hash&gt;</code> "
                "(or <code>grant …</code> / <code>revoke …</code>), as shown in the message that offered it. A tap, "
                "\"yes\" or \"ok\" never approves anything.")
    return None


class Chat:
    """One update's context: tenant, home graph, chat, user, the mapped person."""

    def __init__(self, tenant: str, chat: str, user: str, person: str | None, message_id: int | None):
        self.tenant = tenant
        self.chat, self.user, self.person, self.message_id = chat, user, person, message_id
        self.replies = 0

    @property
    def home(self) -> str:   # resolved only for a mapped user (an unmapped one causes no graph access at all)
        return oncall.home_graph(self.tenant)

    def say(self, lines: list[str] | str, **kw: Any) -> None:
        self.replies += 1
        tg.send_text(self.chat, lines, **kw)


def handle(update: dict, tenant: str | None = None) -> dict:
    t = check_tenant(tenant or settings.faultline_tenant)
    cbq = update.get("callback_query") or None
    msg = update.get("message") or update.get("edited_message") or ((cbq or {}).get("message")) or {}
    user = str(((cbq or update.get("message") or update.get("edited_message") or {}).get("from") or {}).get("id") or "")
    chat = str((msg.get("chat") or {}).get("id") or "")
    uid = update.get("update_id")
    if uid is None or not chat or not user:
        return {"ignored": "not a message or a button"}
    kind = "callback" if cbq else "message"
    person = people_map().get(user)
    c = Chat(t, chat, user, person, msg.get("message_id"))
    text = str(msg.get("text") or "").strip() if not cbq else ""
    # nothing is written for an unmapped user or a chat over its rate limit (security review M19 #5): both checks come
    # before the update is claimed in the graph
    if person is not None and not rate_ok(chat):
        if cbq:
            tg.call("answerCallbackQuery", {"callback_query_id": cbq.get("id"), "text": "Too many requests; wait a minute."})
        return {"refused": "rate limit", "chat": chat}
    if person is not None and not writes.claim_bot_update(gclient.engine().select_graph(c.home), uid=f"tg-{uid}", chat=chat,
                                                          user=user, kind=kind, now=oncall.now_ms()):
        return {"ignored": "duplicate update", "update_id": uid}
    if person is None:
        if not rate_ok(chat):   # an unmapped chat is answered at most at the same rate, and never recorded
            return {"refused": "rate limit", "chat": chat}
        if text.split(" ")[0].split("@")[0].lower() == "/start":
            c.say([f"Chat id <code>{esc(chat)}</code>, your Telegram user id <code>{esc(user)}</code>.",
                   "You are <b>not mapped</b> to a person, so I cannot act for you. The operator adds "
                   f"<code>{esc(user)}:p-…</code> to TELEGRAM_PEOPLE on the server."])
        elif cbq:
            tg.call("answerCallbackQuery", {"callback_query_id": cbq.get("id"), "text": "Not mapped to a person: /start"})
        else:
            c.say("I only act for on-call people the operator mapped (TELEGRAM_PEOPLE). Send /start to see your id.")
        return {"refused": "unmapped user", "chat": chat}
    try:
        if not RO(t, c.home).run("Q-PERSON-1", {"person": person}).rows:
            c.say(f"Your mapped person <code>{esc(person)}</code> is not an active person in this tenant's graph.")
            return {"refused": "inactive person", "chat": chat}
        if cbq:
            return _callback(c, cbq)
        return _message(c, text)
    except GraphError as e:
        log.warning("telegram update %s: graph error %s", uid, type(e).__name__)
        c.say("FalkorDB is unavailable right now; nothing was done.")
        return {"error": "graph unavailable"}


# ------------------------------------------------------------------ messages: commands and typed phrases
def _message(c: Chat, text: str) -> dict:
    if not text:
        c.say("Send a command (/help) or a typed phrase.")
        return {"ignored": "empty"}
    if len(text) > 1000:
        c.say("That is long for a phone; one request at a time, please.")
        return {"refused": "too long"}
    if text.startswith("/"):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower().lstrip("/")
        fn = COMMANDS.get(cmd)
        if fn is None:
            c.say(HELP)
            return {"command": cmd, "unknown": True}
        out = fn(c, arg.strip())
        return {"command": cmd, **(out or {})}
    m = PHRASE.match(text)
    if m:
        verb, code = m.group(1).lower(), m.group(2).lower()
        return {"phrase": verb, **({"approve": _phrase_approve, "grant": _phrase_grant, "revoke": _phrase_revoke}[verb])(c, code)}
    refusal = consent_refusal(text)
    if refusal:
        c.say(refusal)
        return {"refused": "not the phrase"}
    c.say(HELP)
    return {"ignored": "free text"}


def _cmd_start(c: Chat, arg: str) -> dict:
    writes.link_bot_chat(gclient.engine().select_graph(c.home), chat=c.chat, user=c.user, person=c.person, title="",
                         now=oncall.now_ms())
    name = (RO(c.tenant, c.home).run("Q-PERSON-1", {"person": c.person}).rows or [{}])[0].get("name")
    c.say([f"Linked. Chat id <code>{esc(c.chat)}</code>, Telegram user <code>{esc(c.user)}</code> → "
           f"<b>{esc(name)}</b> (<code>{esc(c.person)}</code>).",
           "Pages to you arrive here from now on; information notices arrive silently.", ""] + HELP)
    return {"linked": c.person}


def _cmd_help(c: Chat, arg: str) -> dict:
    c.say(HELP)
    return {}


def _cmd_oncall(c: Chat, arg: str) -> dict:
    out = oncall.oncall_now(c.tenant)
    lines = ["<b>On call now</b> (Q-ONCALL-NOW)"]
    for r in out["rows"]:
        p = r.get("person")
        lines.append(f"• {esc(r.get('team_name') or r['team'])}: " + (f"{esc(p['name'])} (<code>{esc(p['id'])}</code>) "
                                                                      f"until {time.strftime('%a %H:%M UTC', time.gmtime((r['to'] or 0) / 1000))}"
                                                                      if p else "<i>nobody</i>"))
    c.say(lines)
    return {"teams": len(out["rows"])}


def _cmd_pages(c: Chat, arg: str) -> dict:
    rows = [p for p in oncall.list_pages(c.tenant, statuses=["sent", "delivery_failed"])["rows"]
            if p["kind"] in ("page", "escalation")][:10]
    if not rows:
        c.say("No open pages. Quiet shift.")
        return {"pages": 0}
    lines = [f"<b>{len(rows)} open page(s)</b> (Q-PAGES)"]
    kb = []
    for p in rows:
        lines.append(f"• {tg.badge(p['kind'], p['urgency'])} <code>{esc(p['incident'])}</code> → "
                     f"{esc(p['person']['name'])}, ack by {hhmm(p['ack_due_at'])}" + (" (overdue)" if p["overdue"] else ""))
        kb.append([{"text": f"✅ Ack {p['person']['name'] or p['person']['id']} · {p['incident']}"[:60],
                    "callback_data": tg.cb("ack", p["id"])}])
    c.say(lines, keyboard={"inline_keyboard": kb})
    return {"pages": len(rows)}


def _incident_lines(v: dict) -> list[str]:
    a = v.get("acted") or {}
    lines = [f"<b>{esc(clip(v.get('title') or v['incident'], 120))}</b> · <code>{esc(v['incident'])}</code>",
             f"Stage: <b>{esc(v.get('stage'))}</b>", tg.verdict_line(v)]
    lines += [x for x in (tg.ruled_out_line(v), tg.obligation_line(v)) if x]
    if a:
        lines.append(f"Action: {esc(a.get('option'))}: {esc(a.get('verdict') or a.get('status'))}"
                     + (f" ({tg.link(a.get('external_ref') or '', 'PR')})" if a.get("external_ref") else ""))
    if v.get("incident_url"):
        lines.append(tg.link(v["incident_url"], "Incident room"))
    return lines


def _incident_keyboard(ref: str, v: dict) -> dict:
    rows = [[{"text": "🔎 Why", "callback_data": tg.cb("why", ref)}]
            + ([{"text": "🛠 Options", "callback_data": tg.cb("opt", ref)}] if v.get("stage") == "AWAITING_APPROVAL" else []),
            [{"text": "👥 Who fixes", "callback_data": tg.cb("who", ref)},
             {"text": "📖 Runbook", "callback_data": tg.cb("rb", ref)}]]
    if v.get("incident_url"):
        rows.append([{"text": "🔗 Open", "url": v["incident_url"]}])
    return {"inline_keyboard": rows}


def _cmd_incident(c: Chat, arg: str) -> dict:
    inc = arg.split(" ")[0].strip()
    loc = oncall.locate_incident(c.tenant, inc) if re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", inc or "") else None
    if not loc:
        c.say("Usage: /incident &lt;incident id&gt; (an incident this tenant still holds).")
        return {"found": False}
    v = tg.incident_facts(c.tenant, loc["graph"], inc)
    c.say(_incident_lines(v), keyboard=_incident_keyboard(inc, v))
    return {"found": True, "incident": inc}


def _cmd_ack(c: Chat, arg: str) -> dict:
    pid = arg.split(" ")[0].strip()
    if not re.fullmatch(r"pg-[0-9a-f]{6,40}", pid):
        c.say("Usage: /ack &lt;page id&gt; (see /pages).")
        return {"acked": False}
    return _ack(c, pid)


def _ack(c: Chat, pid: str) -> dict:
    hit = oncall.locate_page(c.tenant, pid)
    if hit is None:
        c.say(f"No page <code>{esc(pid)}</code> in this tenant.")
        return {"acked": False}
    graph, row = hit
    res = oncall.ack(c.tenant, graph, pid, c.person, "telegram", tg_user=c.user)
    if not res:
        c.say(f"Page <code>{esc(pid)}</code> is {esc(row.get('status'))}: nothing to acknowledge.")
        return {"acked": False, "status": row.get("status")}
    c.say(f"✅ Acknowledged by {esc(res['name'])}: the escalation of <code>{esc(res['incident'])}</code> stops here.")
    from ..memory import learning

    learning.on_ack(c.tenant, graph, res, via="telegram")   # M21: who answers this family's pages (best effort)
    return {"acked": True, "page": pid}


def _cmd_brain(c: Chat, arg: str) -> dict:
    q = arg.strip()
    if len(q) < 3:
        c.say("Usage: /brain &lt;question&gt;, e.g. /brain who decided the payment timeout?")
        return {"asked": False}
    from .. import api

    try:
        out = api.bot_brain(c.tenant, q[:300], c.user)
    except (ValueError, GraphError) as e:
        c.say(f"The brain could not answer: {esc(type(e).__name__)}.")
        return {"asked": True, "ok": False}
    guard = out.get("guard") or {}
    lines = [f"🧠 <b>{esc(clip(q, 200))}</b>", esc(clip(out.get("answer"), 3000))]
    cites = out.get("citations") or []
    if cites:
        lines.append("Citations (every id was returned by a query of this question): "
                     + ", ".join(f"<code>{esc(x)}</code>" for x in cites[:20]))
    lines.append(f"Citation guard: {'ok' if guard.get('ok') else esc(guard.get('reason') or 'refused')} · "
                 f"answered by {esc(out.get('answered_by'))}")
    c.say(lines)
    return {"asked": True, "ok": bool(guard.get("ok")), "citations": len(cites)}


def _cmd_report(c: Chat, arg: str) -> dict:
    now = oncall.now_ms()
    rep = oncall.report(c.tenant, since=now - 12 * 3_600_000, until=now)
    lines = ["📋 <b>Shift report</b>, last 12 hours (Q-SHIFT-REPORT)", esc(rep["summary"])]
    for inc in rep["incidents"][:8]:
        lines.append(f"• <code>{esc(inc['id'])}</code> {esc(clip(inc.get('title'), 60))}: {esc(inc.get('stage'))}")
    c.say(lines)
    return {"counts": rep["counts"]}


def _cmd_handoff(c: Chat, arg: str) -> dict:
    to, _, note = arg.partition(" ")
    to, note = to.strip(), note.strip()
    if not PERSON_RE.match(to or "") or len(note) < 3:
        c.say("Usage: /handoff &lt;person id&gt; &lt;note&gt;, e.g. /handoff p-017 watch payment latency")
        return {"handed": False}
    try:
        out = oncall.hand_off(c.tenant, from_=c.person, to=to, note=note)
    except ValueError as e:
        c.say(esc(str(e)))
        return {"handed": False}
    c.say(f"📋 Handed over to <code>{esc(to)}</code> (hand-off <code>{esc(out['id'])}</code>); they got a report page.")
    from ..memory import learning

    learning.on_note(c.tenant, "handoff", c.person, key_parts=[out["id"]], to=to, handoff=out["id"], via="telegram")
    return {"handed": True, "handoff": out["id"]}


def _cmd_contracts(c: Chat, arg: str) -> dict:
    rows = [r for r in contracts.listing(c.tenant, c.home)["rows"] if r["status"] in ("active", "exhausted", "expired")][:10]
    if not rows:
        c.say("No standing contracts.")
        return {"contracts": 0}
    lines = ["🌙 <b>Standing approvals</b> (Q-CONTRACTS)"]
    for r in rows:
        params = r.get("params") or {}
        what = (f"flag {params.get('flag')} → {params.get('state')}" if r["action_kind"] == "flip_flag"
                else f"roll back {params.get('revert')}")
        lines.append(f"• <code>{esc(r['id'])}</code> {esc(what)} when the gate confirms a change on {esc(r['family'])}: "
                     f"{r['uses']}/{r['max_uses']} uses, {esc(r['status'])} until "
                     f"{time.strftime('%Y-%m-%d', time.gmtime((r['expires_at'] or 0) / 1000))}"
                     + (f". Revoke: <code>revoke {esc(r['id'][3:9])}</code>" if r["status"] == "active" else ""))
    c.say(lines)
    return {"contracts": len(rows)}


def _dur(ms: Any) -> str:
    if ms is None:
        return "n/a"
    s = int(ms) // 1000
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60} min"


def _cmd_stats(c: Chat, arg: str) -> dict:
    st = oncall.stats(c.tenant, since=oncall.now_ms() - 7 * 86_400_000)
    c.say(["📊 <b>On-call, last 7 days</b> (Q-ONCALL-STATS)",
           f"MTTA {_dur(st['mtta_ms'])} over {st['acked_incidents']} acknowledged incident(s)",
           f"MTTR {_dur(st['mttr_ms'])} over {st['resolved_incidents']} resolved incident(s)",
           f"{st['pages']} page(s) woke {st['people_paged']} person(s); {st['handled_under_contract']} handled under a "
           "standing contract (nobody woken)"])
    return {"stats": True}


def _cmd_mute(c: Chat, arg: str) -> dict:
    try:
        minutes = max(0, min(int(arg.split(" ")[0]), int(weights()["oncall"]["telegram_mute_max_min"])))
    except (ValueError, IndexError):
        c.say(f"Usage: /mute &lt;minutes&gt; (up to {int(weights()['oncall']['telegram_mute_max_min'])}; 0 unmutes). "
              "Pages always ring; only information notices are held back.")
        return {"muted": False}
    g = gclient.engine().select_graph(c.home)
    if not writes.mute_bot_chat(g, chat=c.chat, until=oncall.now_ms() + minutes * 60_000):
        writes.link_bot_chat(g, chat=c.chat, user=c.user, person=c.person, title="", now=oncall.now_ms())
        writes.mute_bot_chat(g, chat=c.chat, until=oncall.now_ms() + minutes * 60_000)
    c.say(f"🔕 Information notices muted for {minutes} min. Pages and escalations still ring." if minutes
          else "🔔 Unmuted.")
    return {"muted": minutes}


COMMANDS = {"start": _cmd_start, "help": _cmd_help, "oncall": _cmd_oncall, "pages": _cmd_pages,
            "incident": _cmd_incident, "ack": _cmd_ack, "brain": _cmd_brain, "report": _cmd_report,
            "handoff": _cmd_handoff, "contracts": _cmd_contracts, "stats": _cmd_stats, "mute": _cmd_mute}


# ------------------------------------------------------------------ buttons
def _resolve(c: Chat, ref: str) -> dict | None:
    """A button's reference: a page id or an incident id → {graph, incident, run, page}."""
    if ref.startswith("pg-"):
        hit = oncall.locate_page(c.tenant, ref)
        if hit is None:
            return None
        graph, row = hit
        loc = oncall.locate_incident(c.tenant, row["incident"]) or {}
        return {"graph": graph, "incident": row["incident"], "run": loc.get("run"), "page": ref}
    loc = oncall.locate_incident(c.tenant, ref)
    return {"graph": loc["graph"], "incident": ref, "run": loc["run"], "page": None} if loc else None


def _callback(c: Chat, cbq: dict) -> dict:
    data = str(cbq.get("data") or "")
    kind, _, rest = data.partition(":")
    ref, _, extra = rest.partition(":")
    answer = "Done"
    try:
        if kind == "ack":
            out = _ack(c, ref)
            answer = "Acknowledged" if out.get("acked") else "Nothing to acknowledge"
        else:
            r = _resolve(c, ref)
            if r is None:
                c.say("That incident or page is gone (collected or unknown).")
                out = {"missing": True}
                answer = "Gone"
            else:
                fn = BUTTONS.get(kind)
                out = fn(c, r, extra) if fn else {"unknown": kind}
                answer = out.pop("_answer", "Done") if isinstance(out, dict) else "Done"
    finally:
        tg.call("answerCallbackQuery", {"callback_query_id": cbq.get("id"), "text": answer[:180]})
    return {"button": kind, **(out or {})}


def _b_escalate(c: Chat, r: dict, extra: str) -> dict:
    out = oncall.escalate_now(c.tenant, r["graph"], r["incident"], by=c.person)
    if out.get("to"):
        from ..memory import learning

        learning.on_note(c.tenant, "escalate_now", c.person, key_parts=[r["graph"], r["incident"], out.get("page")],
                         incident=r["incident"], graph=r["graph"], to=out["to"], via="telegram")
        c.say(f"⏭ Escalated <code>{esc(r['incident'])}</code> to {esc(out['to_name'])} now.")
        return {"escalated_to": out["to"], "_answer": "Escalated"}
    c.say(f"Not escalated: {esc(out.get('why'))}.")
    return {"escalated_to": None, "_answer": "Not escalated"}


def _b_why(c: Chat, r: dict, extra: str) -> dict:
    v = tg.incident_facts(c.tenant, r["graph"], r["incident"])
    lines = [f"🔎 <b>Why</b> · <code>{esc(r['incident'])}</code>", tg.verdict_line(v)]
    if v.get("chain"):
        lines.append(f"Proof path (G2, <code>Q-GATE-1</code>): {esc(' → '.join(v['chain']))}")
    if v.get("checks"):
        lines.append("Gate checks:")
        for ck in v["checks"]:
            mark = "✅" if ck.get("passed") else ("➖" if ck.get("passed") is None else "❌")
            lines.append(f"{mark} {esc(ck.get('name'))} · <code>{esc(ck.get('template'))}</code>: {esc(clip(ck.get('detail'), 140))}")
    tmpl = {c_.get("name", "").split(" ")[0]: c_.get("template") for c_ in v.get("checks") or []}
    for x in v.get("ruled_out") or []:
        lines.append(f"❌ {esc(x['cause'])} ruled out by {esc(x['gate'])} (<code>{esc(tmpl.get(x['gate']) or 'Q-HYP-1')}</code>): "
                     f"{esc(clip(x['reason'], 200))}")
    c.say(lines, reply_to=c.message_id)
    return {"why": True}


def _options(c: Chat, r: dict) -> list[dict]:
    return RO(c.tenant, r["graph"]).run("Q-ACT-1", {"inc": r["incident"]}).rows


def _b_options(c: Chat, r: dict, extra: str) -> dict:
    import json

    stage = (RO(c.tenant, r["graph"]).run("Q-INC-1", {"inc": r["incident"]}).rows or [{}])[0].get("stage")
    opts = _options(c, r)
    lines = [f"🛠 <b>Options</b> · <code>{esc(r['incident'])}</code> (stage {esc(stage)})"]
    kb = []
    for o in opts:
        n = o["id"].rsplit("-", 1)[-1]
        fut = o.get("future")
        fut = json.loads(fut) if isinstance(fut, str) and fut else (fut or {})
        pred = f" · predicted: {esc(fut.get('predicted'))}" if fut.get("predicted") else ""
        if o["enabled"] and o["status"] in ("option", "chosen"):
            lines.append(f"<b>{esc(n)}.</b> {esc(o['option'])}{pred}\n   {esc(clip(o['reason'], 220))}")
            if stage == "AWAITING_APPROVAL":
                kb.append([{"text": f"Choose {n}: {o['option']}"[:60], "callback_data": tg.cb("ch", r["page"] or r["incident"], n)}])
        else:
            lines.append(f"<s>{esc(o['option'])}</s> ({esc(o['status'])}): {esc(clip(o.get('reject_reason') or o['reason'], 160))}")
    lines.append("Choosing shows the exact action and its plan hash; approving then needs the typed phrase.")
    c.say(lines, keyboard={"inline_keyboard": kb} if kb else None, reply_to=c.message_id)
    return {"options": len(opts)}


def _ttl_ms() -> int:
    return int(weights()["oncall"]["contract_offer_ttl_s"]) * 1000


def _b_choose(c: Chat, r: dict, extra: str) -> dict:
    from fastapi import HTTPException

    from .. import api

    aid = f"act-{r['incident']}-{extra}"
    if not any(o["id"] == aid for o in _options(c, r)):
        c.say("That option is not in this incident's plan.")
        return {"chosen": False, "_answer": "Unknown option"}
    try:
        out = api.bot_choose(c.tenant, r["incident"], aid, c.person)
    except HTTPException as e:
        c.say(f"❌ Not chosen: {esc(e.detail)}")
        return {"chosen": False, "_answer": "Not chosen"}
    spec = out["spec"]
    h = spec["plan_hash"]
    now = oncall.now_ms()
    writes.create_bot_proposal(gclient.engine().select_graph(c.home), pid=f"bp-{uuid.uuid4().hex[:14]}", kind="approve",
                               chat=c.chat, user=c.user, person=c.person, tenant=c.tenant, graph=out["graph"],
                               inc=r["incident"], action=aid, hash_=h, now=now, ttl_ms=_ttl_ms(),
                               detail=spec.get("commit", "").splitlines()[0] if spec.get("commit") else spec.get("title", ""))
    args = spec.get("args") or {}
    lines = [f"🛠 <b>Exact action</b> · <code>{esc(r['incident'])}</code>", change_line(spec),
             f"Repo <code>{esc(args.get('repo'))}</code>" + (f" · file <code>{esc(spec.get('file'))}</code>" if spec.get("file") else "")
             + (f" · branch <code>{esc(spec.get('branch'))}</code>" if spec.get("branch") else "")]
    if spec.get("rollback"):
        lines.append(f"Rollback: {esc(spec['rollback'])}")
    if args.get("reviewers"):
        lines.append(f"Suggested reviewers: {esc(', '.join(args['reviewers']))}")
    lines += [f"Approver check (Q-APPROVER-1): {esc(out['approver']['reason'])}",
              f"Plan hash <code>{esc(h[:16])}…</code>",
              f"To approve, reply exactly: <code>approve {esc(h[:6])}</code> (until {hhmm(now + _ttl_ms())}). "
              "A tap, \"yes\" or \"ok\" never approves."]
    c.say(lines, force_reply=True, reply_to=c.message_id, silent=False)
    return {"chosen": True, "action": aid, "_answer": "Reply with the phrase to approve"}


def change_line(spec: dict) -> str:
    """The exact change an action makes, built from raw values and escaped exactly once."""
    args = spec.get("args") or {}
    change = (f"flags.{args.get('flag')}.state → {args.get('state')}" if spec.get("kind") == "flip_flag" else
              f"revert {args.get('revert')} on {args.get('service')}" if spec.get("kind") == "rollback_deploy" else
              str(spec.get("title") or spec.get("kind")))
    return f"<b>{esc(spec.get('kind'))}</b>: {esc(change)}"


def runbook_line(rb: dict) -> str:
    steps = rb.get("steps")
    steps = "; ".join(str(x) for x in steps) if isinstance(steps, list) else steps
    return (f"• <b>{esc(clip(rb.get('title'), 100))}</b> (<code>{esc(rb.get('id'))}</code>, {esc(rb.get('source'))}, "
            f"support {esc(rb.get('support'))})" + (f": {esc(clip(steps, 300))}" if steps else ""))


def _b_who(c: Chat, r: dict, extra: str) -> dict:
    v = tg.incident_facts(c.tenant, r["graph"], r["incident"])
    lines = [f"👥 <b>Who fixes it</b> · <code>{esc(r['incident'])}</code> (algo.HarmonicCentrality, who_fixes)"]
    for k, w in enumerate(v.get("who") or [], 1):
        lines.append(f"{k}. {esc(w.get('name'))} (<code>{esc(w.get('person'))}</code>) score {float(w.get('score') or 0):.3f}: "
                     f"{esc(clip('; '.join(w.get('reasons') or []), 200))}")
    if len(lines) == 1:
        lines.append("No ranking recorded for this incident.")
    c.say(lines, reply_to=c.message_id)
    return {"who": len(lines) - 1}


def _b_runbook(c: Chat, r: dict, extra: str) -> dict:
    v = tg.incident_facts(c.tenant, r["graph"], r["incident"])
    ids = [x for x in ([v["chain"][1]] if len(v.get("chain") or []) > 1 else []) + list(v.get("targets") or []) if x][:10]
    rows = RO(c.tenant, r["graph"]).run("Q-MEM-3", {"ids": ids}).rows if ids else []
    lines = [f"📖 <b>Runbooks</b> for {esc(', '.join(ids)) or 'this incident'} (Q-MEM-3; derived ones first)"]
    lines += [runbook_line(rb) for rb in rows[:6]]
    if not rows:
        lines.append("No runbook covers these components (a gap the brain lists under missing guardrails).")
    c.say(lines, reply_to=c.message_id)
    return {"runbooks": len(rows)}


def _b_contract(c: Chat, r: dict, extra: str) -> dict:
    from fastapi import HTTPException

    from .. import api

    try:
        offer = api.bot_contract_offer(c.tenant, r["incident"], c.person, 3, 7)
    except HTTPException as e:
        c.say(f"❌ No contract offered: {esc(e.detail)}")
        return {"offered": False, "_answer": "Not offered"}
    now = oncall.now_ms()
    writes.create_bot_proposal(gclient.engine().select_graph(c.home), pid=f"bp-{uuid.uuid4().hex[:14]}", kind="grant",
                               chat=c.chat, user=c.user, person=c.person, tenant=c.tenant, graph=r["graph"],
                               inc=r["incident"], action=offer["action"], hash_=offer["hash"], now=now, ttl_ms=_ttl_ms(),
                               detail=offer["quote"])
    c.say([f"🌙 <b>Standing approval offered</b> · <code>{esc(r['incident'])}</code>", esc(offer["quote"]),
           f"To grant it, reply exactly: <code>grant {esc(offer['hash'][:6])}</code> (until {hhmm(now + _ttl_ms())})."],
          force_reply=True, reply_to=c.message_id, silent=False)
    return {"offered": True, "_answer": "Reply with the phrase to grant"}


BUTTONS = {"esc": _b_escalate, "why": _b_why, "opt": _b_options, "ch": _b_choose, "who": _b_who, "rb": _b_runbook,
           "ct": _b_contract}


# ------------------------------------------------------------------ typed consent
def _proposal(c: Chat, kind: str, code: str) -> dict | None:
    rows = RO(c.tenant, c.home).run("Q-BOT-PROPOSAL", {"chat": c.chat, "kind": kind, "prefix": code,
                                                       "now": oncall.now_ms()}).rows
    return rows[0] if rows else None


def _phrase_approve(c: Chat, code: str) -> dict:
    from fastapi import HTTPException

    from .. import api

    p = _proposal(c, "approve", code)
    if p is None:
        c.say(f"No open proposal with code <code>{esc(code)}</code> in this chat: it expired, was used, or was never "
              "chosen here. Tap 🛠 Options → Choose again.")
        return {"approved": False, "why": "no proposal"}
    if p["user"] != c.user or not writes.use_bot_proposal(gclient.engine().select_graph(c.home), pid=p["id"], chat=c.chat,
                                                          user=c.user, now=oncall.now_ms()):
        c.say("That proposal belongs to another user, or was just used. Choose again.")
        return {"approved": False, "why": "not yours or used"}
    try:
        out = api.bot_approve(c.tenant, p["incident"], p["action"], p["hash"], c.person, c.user)
    except HTTPException as e:
        c.say(f"❌ Not approved: {esc(e.detail)}")
        return {"approved": False, "why": str(e.detail)[:200]}
    c.say(f"✅ Approved by {esc(out['approver']['name'])} via Telegram: executing <code>{esc(p['action'])}</code>. "
          "Verification runs through GitHub main and telemetry; the page card updates when it is done.", silent=False)
    return {"approved": True, "action": p["action"], "incident": p["incident"]}


def _phrase_grant(c: Chat, code: str) -> dict:
    from fastapi import HTTPException

    from .. import api

    p = _proposal(c, "grant", code)
    if p is None:
        c.say(f"No open contract offer with code <code>{esc(code)}</code> in this chat (expired or used).")
        return {"granted": False}
    if p["user"] != c.user or not writes.use_bot_proposal(gclient.engine().select_graph(c.home), pid=p["id"], chat=c.chat,
                                                          user=c.user, now=oncall.now_ms()):
        c.say("That offer belongs to another user, or was just used.")
        return {"granted": False}
    try:
        out = api.bot_contract_grant(c.tenant, p["incident"], p["hash"], c.person)
    except HTTPException as e:
        c.say(f"❌ Not granted: {esc(e.detail)}")
        return {"granted": False}
    ct = out["contract"]
    c.say(f"🌙 Granted <code>{esc(ct['id'])}</code>: {ct['max_uses']} use(s) until "
          f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(ct['expires_at'] / 1000))}. Revoke any time: "
          f"<code>revoke {esc(ct['id'][3:9])}</code>", silent=False)
    return {"granted": True, "contract": ct["id"]}


def _phrase_revoke(c: Chat, code: str) -> dict:
    rows = [r for r in contracts.listing(c.tenant, c.home)["rows"] if r["status"] == "active" and r["id"][3:9] == code]
    if len(rows) != 1:
        c.say(f"No single active contract matches <code>{esc(code)}</code> (/contracts lists them).")
        return {"revoked": False}
    ok = contracts.revoke(home=c.home, cid=rows[0]["id"], by=f"{c.person} (telegram {c.user})")
    c.say(f"Revoked <code>{esc(rows[0]['id'])}</code>: the next such incident pages a human." if ok
          else "It was no longer active.")
    return {"revoked": ok, "contract": rows[0]["id"]}


def prune(tenant: str, now_ms: int | None = None) -> int:
    """TTL clean-up in the on-call graph (the tick runs it): processed updates past weights.yaml
    oncall.bot_update_ttl_h, consents a day past their expiry, hourly budget counters older than two days."""
    now = oncall.now_ms() if now_ms is None else int(now_ms)
    ttl = int(weights()["oncall"]["bot_update_ttl_h"]) * 3_600_000
    return writes.prune_bot_state(gclient.engine().select_graph(oncall.home_graph(check_tenant(tenant))),
                                  updates_before=now - ttl, proposals_before=now - 86_400_000,
                                  budget_before=now - 2 * 86_400_000)


# ------------------------------------------------------------------ the morning digest
def digest_due(now_ms: int) -> bool:
    h = int(settings.telegram_digest_hour)
    return 0 <= h <= 23 and time.gmtime(now_ms / 1000).tm_hour == h


def maybe_digest(tenant: str, now_ms: int | None = None) -> dict | None:
    """Once a day at TELEGRAM_DIGEST_HOUR (UTC): the shift report to the shared chat and every linked chat, silently.
    Sent once per day per tenant (claimed in the graph like an update)."""
    t = check_tenant(tenant)
    now = oncall.now_ms() if now_ms is None else int(now_ms)
    if not tg.configured() or not digest_due(now):
        return None
    home = oncall.home_graph(t)
    day = time.strftime("%Y-%m-%d", time.gmtime(now / 1000))
    if not writes.claim_bot_update(gclient.engine().select_graph(home), uid=f"digest-{t}-{day}", chat="*", user="*",
                                   kind="digest", now=now):
        return None
    rep = oncall.report(t, since=now - 24 * 3_600_000, until=now)
    st = oncall.stats(t, since=now - 24 * 3_600_000)
    lines = [f"☀️ <b>Morning report</b> · {esc(day)} (last 24 hours, Q-SHIFT-REPORT)", esc(rep["summary"]),
             f"MTTA {_dur(st['mtta_ms'])}, MTTR {_dur(st['mttr_ms'])}; {st['handled_under_contract']} fixed under a "
             "standing contract while nobody was woken."]
    chats = {str(r["chat"]) for r in RO(t, home).run("Q-BOT-CHATS", {"person": ""}).rows}
    if settings.telegram_chat_id:
        chats.add(str(settings.telegram_chat_id))
    for chat in sorted(chats):
        tg.send_text(chat, lines, silent=True)
    return {"sent": len(chats), "day": day}


__all__ = ["handle", "people_map", "rate_ok", "consent_refusal", "maybe_digest", "digest_due", "prune", "PHRASE", "HELP"]
