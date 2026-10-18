"""Telegram on-call bot, the outbound half: the Bot API client, HTML formatting within Telegram's limits, and the page
card, read from the graph and edited IN PLACE as the incident moves (acked, escalated, approved, APPLIED, resolved,
fixed under a standing contract): one bot, buttons on the page, never raises. Everything a card says is read through
the RO templates (Q-PAGE-ONE, Q-INC-1, Q-CAUSE-1, Q-INC-GATES, Q-HYP-1, Q-EV-TOOL, Q-ACT-1, Q-ACT-APPROVER), and the
only write is the message mapping on the Page.

The bot token (TELEGRAM_BOT_TOKEN, .env only) is read in exactly one place, `_http`, to build the request URL. It is
never logged, returned or written anywhere: errors are reported by their type or by Telegram's own description (which
never contains it), and `scrub` removes it from any text that might.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

from ..config import settings
from ..graph import client as gclient
from ..graph import writes
from ..graph.errors import GraphNotReady
from ..graph.ro import RO

log = logging.getLogger("faultline.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_S = 8
LIMIT = 4096          # Telegram's message limit (characters after entity parsing)
SAFE = 3900           # what we send at most, counted on the HTML source (always longer than what Telegram counts)
CALLBACK_MAX = 64     # bytes of callback_data

COMMANDS = [
    ("start", "Link this chat and show its id and your mapping"),
    ("oncall", "Who is on call now, per team"),
    ("pages", "Open pages, each with an Ack button"),
    ("incident", "Status card of an incident: /incident <id>"),
    ("ack", "Acknowledge a page: /ack <page id>"),
    ("brain", "Ask the company brain: /brain <question>"),
    ("report", "The shift report (last 12 hours)"),
    ("handoff", "Hand the shift over: /handoff <person> <note>"),
    ("contracts", "Standing approvals, and how to revoke one"),
    ("stats", "MTTA, MTTR, people woken, handled under contract"),
    ("mute", "Silence information notices: /mute <minutes> (pages still ring)"),
    ("help", "What the bot does and how approving works"),
]
DESCRIPTION = ("Faultline's on-call pager. No path, no claim: a page says which change caused the incident only when "
               "FalkorDB proves a causal path and enough capacity, and names the look-alikes it ruled out. Acknowledge, "
               "see the proof, choose a containment and approve it by typing the exact phrase; nothing changes without "
               "a human, except a fix a human approved to repeat (a standing contract), which is still verified.")
SHORT_DESCRIPTION = "On-call pages that come with proof. No path, no claim."


# ------------------------------------------------------------------ the Bot API (token used only here)
def configured() -> bool:
    return bool(settings.telegram_bot_token)


def scrub(text: str) -> str:
    tok = settings.telegram_bot_token
    return text.replace(tok, "<token>") if tok and isinstance(text, str) else text


def _http(method: str, payload: dict) -> dict:
    """The one place the token is used (the request URL). Tests replace this function."""
    req = urllib.request.Request(API.format(token=settings.telegram_bot_token, method=method),
                                 data=json.dumps(payload).encode(), headers={"content-type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https endpoint
        return dict(json.loads(resp.read().decode()))


def call(method: str, payload: dict) -> dict:
    """One Bot API call. Never raises (a chat outage must never break a page, an ack or a tick); the result is
    Telegram's JSON or {"ok": False, "description": …} without the token."""
    if not configured():
        return {"ok": False, "description": "no bot token (TELEGRAM_BOT_TOKEN)"}
    try:
        return _http(method, payload)
    except urllib.error.HTTPError as e:  # Telegram's error JSON names the problem; the URL (with the token) is dropped
        try:
            body = json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            body = {}
        desc = scrub(str(body.get("description") or f"HTTP {e.code}"))[:300]
        log.warning("telegram %s failed: %s", method, desc)
        return {"ok": False, "description": desc, "error_code": e.code}
    except Exception as e:  # noqa: BLE001 - network, timeout, bad JSON: the type only (messages can carry the URL)
        log.warning("telegram %s failed: %s", method, type(e).__name__)
        return {"ok": False, "description": type(e).__name__}


# ------------------------------------------------------------------ formatting (pure)
def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def attr(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def clip(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"


def base_url() -> str:
    b = settings.faultline_public_url.rstrip("/")
    return b if re.match(r"^https?://", b) and "localhost" not in b and "127.0.0.1" not in b else ""


def link(url: str, label: str) -> str:
    return f'<a href="{attr(url)}">{esc(label)}</a>' if url and re.match(r"^https?://", url) else ""


def _trim_line(line: str, limit: int) -> str:
    """A single line too long for a message: its text without tags, cut, with no half entity left."""
    plain = re.sub(r"<[^>]+>", "", line)
    cut = plain[: max(0, limit - 1)]
    cut = re.sub(r"&[#A-Za-z0-9]*$", "", cut)
    return cut + "…"


def fit(lines: Iterable[str], limit: int = SAFE) -> str:
    """One message: whole lines while they fit, then a note that the rest was trimmed. Never above `limit`."""
    out, size = [], 0
    note = "… (trimmed: open the incident for the rest)"
    for ln in lines:
        if len(ln) > limit:
            ln = _trim_line(ln, limit - len(note) - 2)
        if size + len(ln) + 1 > limit - len(note) - 1:
            out.append(note)
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out)[:limit]


def split(lines: Iterable[str], limit: int = SAFE) -> list[str]:
    """Several messages for a long answer, each within `limit`, cut only between lines."""
    chunks, cur, size = [], [], 0
    for ln in lines:
        if len(ln) > limit:
            ln = _trim_line(ln, limit)
        if cur and size + len(ln) + 1 > limit:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [""]


def hhmm(ms: Any) -> str:
    try:
        return time.strftime("%H:%M UTC", time.gmtime(int(ms) / 1000))
    except (TypeError, ValueError):
        return "?"


def cb(kind: str, ref: str, *extra: Any) -> str:
    data = ":".join([kind, ref, *[str(x) for x in extra]])
    if len(data.encode()) > CALLBACK_MAX:
        raise ValueError(f"callback data over {CALLBACK_MAX} bytes: {data!r}")
    return data


BADGE = {("page", "urgent"): "🔴 URGENT", ("page", "normal"): "🟠 PAGE", ("escalation", "urgent"): "🆘 ESCALATED",
         ("escalation", "normal"): "🆘 ESCALATED", ("contract_notice", None): "🌙 HANDLED UNDER CONTRACT",
         ("report", None): "📋 HAND-OFF"}


def badge(kind: str, urgency: str | None) -> str:
    return BADGE.get((kind, urgency)) or BADGE.get((kind, None)) or "🔔 PAGE"


def verdict_line(v: dict) -> str:
    if v.get("cause"):
        chain = " → ".join(v.get("chain") or [])
        return f"<b>{esc(v['cause'])} caused this</b>" + (f": {esc(chain)}" if chain else "")
    return f"<b>No cause confirmed by the gate</b> (stage {esc(v.get('stage'))}): a human decides"


def ruled_out_line(v: dict) -> str:
    items = [f"{esc(x['cause'])} ({esc(x['gate'])}: {esc(x['short'])})" for x in (v.get("ruled_out") or [])[:4]]
    return ("❌ Ruled out: " + "; ".join(items)) if items else ""


def obligation_line(v: dict) -> str:
    o = v.get("obligations") or {}
    b = o.get("breach") or {}
    parts = []
    if b.get("breach_in_min") is not None:
        parts.append(f"{esc(b.get('slo'))} breaches in ~{float(b['breach_in_min']):.0f} min")
    if o.get("customers_reached"):
        parts.append(f"{int(o['customers_reached'])} customer(s), {float(o.get('revenue_at_risk') or 0):,.0f} MRR at risk")
    return ("⏳ " + " · ".join(parts)) if parts else ""


def state_line(v: dict) -> str:
    p, a = v["page"], v.get("acted") or {}
    stage = v.get("stage")
    if a.get("verdict") == "APPLIED" and stage == "RESOLVED":
        pr = link(a.get("external_ref") or "", "PR") or esc(a.get("external_ref") or "")
        if str(a.get("approver") or "").startswith("contract:"):
            return (f"🌙 <b>Fixed while you slept</b>: {esc(a.get('option'))} under standing contract "
                    f"{esc(str(a['approver']).removeprefix('contract:'))}, verified APPLIED" + (f" ({pr})" if pr else ""))
        return (f"✅ <b>Resolved</b>: {esc(a.get('option'))} verified APPLIED" + (f" ({pr})" if pr else "")
                + (f", approved by {esc(a.get('approver_name') or a.get('approver'))}" if a.get("approver") else ""))
    if stage in ("EXECUTE", "VERIFY", "WRITEBACK", "LEARN") and a:
        return (f"🛠 Approved by {esc(a.get('approver_name') or a.get('approver'))}"
                + (" (Telegram)" if a.get("via") == "telegram" else "") + f": {esc(a.get('option'))}, executing")
    if stage == "UNKNOWN_ESCALATED":
        return "⚠️ <b>Handed to a human</b>" + (f": {esc(a.get('verdict'))} after approval" if a.get("verdict") else "")
    st = p.get("status")
    if st == "acked":
        return (f"✅ Acknowledged by {esc(p.get('acked_by_name') or p.get('acked_by') or p.get('ack_actor'))} via "
                f"{esc(p.get('ack_via'))} at {hhmm(p.get('acked_at'))}")
    if st == "escalated":
        return f"⏭ Escalated to {esc(v.get('escalated_to_name') or p.get('escalated_to'))} at {hhmm(p.get('escalated_at'))}"
    if st == "superseded":
        return f"↪ {esc(clip(p.get('detail'), 160))}"
    if st == "resolved":
        return "✅ Resolved"
    if p.get("kind") in ("page", "escalation"):
        return f"⏰ Ack by {hhmm(p.get('ack_due_at'))} or it escalates" + (" (delivery failed)" if st == "delivery_failed" else "")
    return ""


def page_card(v: dict) -> tuple[str, dict]:
    """The page as one phone-sized HTML message plus its inline keyboard (pure: tests render it from a dict). A wave of
    pages that share a chat (`v["pages"]`, more than one) is ONE card listing everyone paged (wave_card)."""
    if len(v.get("pages") or []) > 1:
        return wave_card(v)
    p = v["page"]
    kind = p.get("kind") or "page"
    lines = [f"{badge(kind, p.get('urgency'))} · <code>{esc(v.get('incident'))}</code>",
             f"<b>{esc(clip(v.get('title') or v.get('incident'), 120))}</b>"]
    if kind == "report":
        lines += [f"From {esc(clip(p.get('reason'), 120))}", esc(clip(p.get("detail"), 1500))]
    else:
        lines.append(verdict_line(v))
        lines += [x for x in (ruled_out_line(v), obligation_line(v)) if x]
        if kind != "contract_notice":
            lines.append(f"👤 Why you: {esc(clip(p.get('reason'), 220))}")
        if kind == "escalation" or "after approval" in str(p.get("detail") or ""):
            lines.append(f"📝 {esc(clip(p.get('detail'), 400))}")
    st = state_line(v)
    if st:
        lines.append(st)
    links = " · ".join(x for x in (link(v.get("phone_url") or "", "Phone page"),
                                   link(v.get("incident_url") or "", "Incident room")) if x)
    if links:
        lines.append(links)
    return fit(lines), keyboard(v)


_STATUS_MARK = {"acked": " · ✅ acknowledged", "escalated": " · ⏭ escalated", "resolved": " · resolved",
                "delivery_failed": " · delivery failed"}


def wave_card(v: dict) -> tuple[str, dict]:
    """One card for everyone a wave paged into the same chat (coalesced delivery): the incident once, then each paged
    person with their reason, their state and their own phone page (signed ack link). Pure."""
    pages = v["pages"]
    lead = pages[0]
    kind = lead.get("kind") or "page"
    urgency = "urgent" if any(q.get("urgency") == "urgent" for q in pages) else lead.get("urgency")
    lines = [f"{badge(kind, urgency)} · <code>{esc(v.get('incident'))}</code> · {len(pages)} people paged",
             f"<b>{esc(clip(v.get('title') or v.get('incident'), 120))}</b>", verdict_line(v)]
    lines += [x for x in (ruled_out_line(v), obligation_line(v)) if x]
    lines.append(f"👥 Paged ({len(pages)}):")
    for q in pages:
        ph = link((v.get("phone_urls") or {}).get(q["id"], ""), "page")
        lines.append(f"• <b>{esc(q.get('person_name') or q.get('person'))}</b> (<code>{esc(q.get('person'))}</code>): "
                     f"{esc(clip(q.get('reason'), 160))}{_STATUS_MARK.get(q.get('status'), '')}" + (f" · {ph}" if ph else ""))
    if kind == "escalation" or "after approval" in str(lead.get("detail") or ""):
        lines.append(f"📝 {esc(clip(lead.get('detail'), 400))}")
    st = state_line(v)
    if st:
        lines.append(st)
    if v.get("incident_url"):
        lines.append(link(v["incident_url"], "Incident room"))
    return fit(lines), keyboard(v)


def _common_rows(v: dict, ref: str) -> list[list[dict]]:
    p, a = v["page"], v.get("acted") or {}
    rows: list[list[dict]] = []
    resolved = v.get("stage") == "RESOLVED"
    if p.get("kind") != "report":
        rows.append([{"text": "🔎 Why", "callback_data": cb("why", ref)}]
                    + ([{"text": "🛠 Options", "callback_data": cb("opt", ref)}]
                       if v.get("stage") == "AWAITING_APPROVAL" else []))
        rows.append([{"text": "👥 Who fixes", "callback_data": cb("who", ref)},
                     {"text": "📖 Runbook", "callback_data": cb("rb", ref)}])
    if resolved and a.get("verdict") == "APPLIED" and a.get("kind") in ("flip_flag", "rollback_deploy") \
            and not str(a.get("approver") or "").startswith("contract:"):
        rows.append([{"text": "🌙 Grant a contract for repeats", "callback_data": cb("ct", ref)}])
    if v.get("incident_url"):
        rows.append([{"text": "🔗 Open", "url": v["incident_url"]}])
    return rows


def keyboard(v: dict) -> dict:
    pages = v.get("pages") or []
    if len(pages) > 1:   # a combined card: acknowledging stays per person
        ref = pages[0]["id"]
        open_ = [q for q in pages if q.get("status") in ("sent", "delivery_failed") and q.get("kind") in ("page", "escalation")]
        rows: list[list[dict]] = []
        if open_ and v.get("stage") != "RESOLVED":
            mine = next((q for q in open_ if q.get("person") and q.get("person") == v.get("chat_person")), None)
            if mine:   # the chat's own person was paged: the card's Ack acts for that person
                rows.append([{"text": "✅ Acknowledge", "callback_data": cb("ack", mine["id"])},
                             {"text": "⏭ Escalate now", "callback_data": cb("esc", ref)}])
            else:      # a shared chat: one button per paged person; the bot records who tapped it (acked_by, tg_user)
                rows += [[{"text": clip(f"✅ Ack: {q.get('person_name') or q.get('person')}", 40),
                           "callback_data": cb("ack", q["id"])}] for q in open_[:8]]
                rows.append([{"text": "⏭ Escalate now", "callback_data": cb("esc", ref)}])
        return {"inline_keyboard": rows + _common_rows(v, ref)}
    p = v["page"]
    ref = p["id"]
    rows = []
    open_ = p.get("status") in ("sent", "delivery_failed") and p.get("kind") in ("page", "escalation")
    resolved = v.get("stage") == "RESOLVED"
    if open_ and not resolved:
        rows.append([{"text": "✅ Acknowledge", "callback_data": cb("ack", ref)},
                     {"text": "⏭ Escalate now", "callback_data": cb("esc", ref)}])
    return {"inline_keyboard": rows + _common_rows(v, ref)}


def digest(text: str, kb: dict) -> str:
    return hashlib.sha256((text + json.dumps(kb, sort_keys=True)).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ views read from the graph
_GATE_SHORT = {"G2": "no causal path", "G5": "cannot carry the impact", "G3": "outside the time window",
               "G4": "no measured anomaly", "G6": "competitor", "G1": "not grounded"}


def incident_facts(tenant: str, graph: str, inc: str) -> dict:
    """What a card says about an incident, every part read through a template."""
    from . import oncall

    ro = RO(tenant, graph)
    row = (ro.run("Q-INC-1", {"inc": inc}).rows or [{}])[0]
    cause = (ro.run("Q-CAUSE-1", {"inc": inc}).rows or [{}])[0].get("cause")
    chain: list[str] = []
    checks: list[dict] = []
    for g in reversed(ro.run("Q-INC-GATES", {"inc": inc}).rows):
        if g["passed"] and g["cause"] == cause:
            checks = json.loads(g["checks"] or "[]")
            g2 = next((c for c in checks if c.get("name") == "G2 path" and c.get("passed")), None)
            if g2:
                chain = [x.strip() for x in str(g2.get("detail") or "").split(" ; ")[0].split(" (learned")[0].split("→") if x.strip()]
            break
    ruled = []
    for h in ro.run("Q-HYP-1", {"inc": inc}).rows:
        if h["status"] == "eliminated":
            m = re.match(r"^(G\d)", str(h.get("reason") or ""))
            gate = m.group(1) if m else "gate"
            ruled.append({"cause": h["cause"], "gate": gate, "short": _GATE_SHORT.get(gate, "eliminated"),
                          "reason": h.get("reason")})
    loc = oncall.locate_incident(tenant, inc) or {}
    obligations, who = {}, []
    if loc.get("run"):
        for tool in ("obligation_clock", "who_fixes"):
            ev = ro.run("Q-EV-TOOL", {"run": loc["run"], "tool": tool}).rows
            if ev and ev[0]["payload"]:
                payload = json.loads(ev[0]["payload"])
                if tool == "obligation_clock":
                    obligations = {"breach": payload.get("breach"), "customers_reached": payload.get("customers_reached"),
                                   "revenue_at_risk": payload.get("revenue_at_risk"), "template": ev[0]["template"]}
                else:
                    who = payload.get("rows", [])[:5]
    acted = {}
    for a in ro.run("Q-ACT-1", {"inc": inc}).rows:
        if a.get("approval_id"):
            ap = (ro.run("Q-ACT-APPROVER", {"inc": inc, "aid": a["id"]}).rows or [{}])[0]
            acted = {"id": a["id"], "option": a["option"], "kind": a["kind"], "verdict": a["verdict"],
                     "external_ref": a["external_ref"], "approver": ap.get("approver"), "status": a["status"]}
    if acted.get("approver") and not str(acted["approver"]).startswith("contract:"):
        pr = (ro.run("Q-PERSON-1", {"person": acted["approver"]}).rows or [{}])[0]
        acted["approver_name"] = pr.get("name")
    return {"incident": inc, "title": row.get("title"), "stage": row.get("stage"), "targets": row.get("targets") or [],
            "cause": cause, "chain": chain, "checks": checks, "ruled_out": ruled, "obligations": obligations, "who": who,
            "acted": acted, "run": loc.get("run"), "graph": graph,
            "incident_url": f"{base_url()}/incidents/{inc}?tenant={tenant}" if base_url() else ""}


def page_view(tenant: str, graph: str, pid: str) -> dict | None:
    from . import oncall

    ro = RO(tenant, graph)
    rows = ro.run("Q-PAGE-ONE", {"page": pid, "now": oncall.now_ms()}).rows
    if not rows:
        return None
    p = rows[0]
    if p.get("kind") == "report" or not p.get("incident_stage"):   # a hand-off note: no incident behind it here
        v = {"incident": p.get("incident") or "shift", "title": "Shift hand-off", "stage": None, "graph": graph,
             "incident_url": ""}
    else:
        v = incident_facts(tenant, graph, p["incident"])
    v["page"] = p
    if p.get("escalated_to"):
        nx = ro.run("Q-PAGE-ONE", {"page": p["escalated_to"], "now": oncall.now_ms()}).rows
        v["escalated_to_name"] = nx[0]["person_name"] if nx else None
    v["phone_url"] = oncall.deep_link(tenant, pid, issued_at=p.get("sent_at")) if base_url() else ""
    return v


def wave_view(tenant: str, graph: str, pids: list[str], chat_person: str | None = None) -> dict | None:
    """What a card shows for a wave of pages that share one chat: the incident (from the first page), every page of
    the wave (Q-PAGE-ONE each, in id order so a re-render is stable) and the chat's own person (whose Ack the card
    offers). One page: the single-page view."""
    from . import oncall

    pids = sorted(set(pids))
    v = page_view(tenant, graph, pids[0])
    if v is None:
        return None
    v["chat_person"] = chat_person
    if len(pids) == 1:
        return v
    ro = RO(tenant, graph)
    pages = [r for pid in pids for r in ro.run("Q-PAGE-ONE", {"page": pid, "now": oncall.now_ms()}).rows]
    v["pages"] = pages
    v["page"] = next((q for q in pages if q.get("status") == "acked"), pages[0])   # the state line reads the ack
    v["phone_urls"] = ({q["id"]: oncall.deep_link(tenant, q["id"], issued_at=q.get("sent_at")) for q in pages}
                       if base_url() else {})
    v["phone_url"] = ""
    return v


# ------------------------------------------------------------------ delivery: send once, then edit in place
def chat_person(tenant: str, chat: str | int | None) -> str | None:
    """The person a chat is linked to (/start, Q-BOT-CHAT), or None (a shared chat nobody linked)."""
    from . import oncall

    if not chat:
        return None
    try:
        rows = RO(tenant, oncall.home_graph(tenant)).run("Q-BOT-CHAT", {"id": f"tgchat-{chat}"}).rows
    except GraphNotReady:
        rows = []
    return rows[0].get("person") if rows else None


def group_by_chat(tenant: str, graph: str, pids: list[str]) -> list[tuple[str | None, dict, list[str]]]:
    """Coalescing: the chat each page of a wave goes to (the paged person's linked chat, else the shared chat),
    grouped, so pages for the same incident and wave that land in the same chat become ONE card. [(chat, the chat's
    info: linked row or {}, page ids)] in first-seen order; chat None = nowhere to send."""
    from . import oncall

    ro = RO(tenant, graph)
    groups: dict[str | None, tuple[str | None, dict, list[str]]] = {}
    for pid in pids:
        row = (ro.run("Q-PAGE-ONE", {"page": pid, "now": oncall.now_ms()}).rows or [{}])[0]
        chat, info = chat_for(tenant, row.get("person"))
        key = str(chat) if chat else None
        if key not in groups:
            groups[key] = (chat, info, [])
        groups[key][2].append(pid)
    return list(groups.values())


def chat_for(tenant: str, person: str | None) -> tuple[str | None, dict]:
    """Where a page to `person` goes: the chat that person linked with /start, else the shared on-call chat."""
    from . import oncall

    if person:
        try:
            rows = RO(tenant, oncall.home_graph(tenant)).run("Q-BOT-CHATS", {"person": person}).rows
        except GraphNotReady:
            rows = []
        if rows:
            return str(rows[0]["chat"]), rows[0]
    return (settings.telegram_chat_id or None), {}


def send_text(chat: str | int, lines: Iterable[str] | str, *, keyboard: dict | None = None, silent: bool = True,
              reply_to: int | None = None, force_reply: bool = False) -> list[dict]:
    chunks = split([lines] if isinstance(lines, str) else list(lines))
    out = []
    for k, chunk in enumerate(chunks):
        payload: dict = {"chat_id": chat, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True,
                         "disable_notification": bool(silent)}
        if reply_to and k == 0:
            payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        if k == len(chunks) - 1:
            if keyboard:
                payload["reply_markup"] = keyboard
            elif force_reply:
                payload["reply_markup"] = {"force_reply": True, "input_field_placeholder": "type the exact phrase"}
        out.append(call("sendMessage", payload))
    return out


def send_page(tenant: str, graph: str, pid: str) -> dict:
    """Deliver one page as its card (a wave of one)."""
    chat, info = chat_for(tenant, (RO(tenant, graph).run("Q-PAGE-ONE", {"page": pid, "now": _now()}).rows or [{}])[0]
                          .get("person"))
    if not chat:
        return {"ok": False, "error": "no Telegram chat for the paged person (/start the bot, or set TELEGRAM_CHAT_ID)"}
    return send_group(tenant, graph, chat, info, [pid])


def _now() -> int:
    from . import oncall

    return oncall.now_ms()


def send_group(tenant: str, graph: str, chat: str, info: dict, pids: list[str]) -> dict:
    """Deliver the pages of one wave that share `chat` as ONE card (one page: its own card). Pages and escalations
    always ring; information notices (a fix under a standing contract, a hand-off) arrive silently, and not at all to a
    chat muted with /mute. Every page of the group records the same message (chat, id, digest), so the card is edited
    in place as one. Returns the delivery result recorded on each Page."""
    v = wave_view(tenant, graph, pids, chat_person=(info or {}).get("person") or chat_person(tenant, chat))
    if v is None:
        return {"ok": False, "error": "page not found"}
    muted = bool((info or {}).get("muted_until") and int(info["muted_until"]) > _now())
    loud = (v.get("pages") or [v["page"]])[0].get("kind") in ("page", "escalation")
    if muted and not loud:   # /mute holds back information notices only; a page always rings
        return {"ok": True, "chat": "linked", "muted_until": int(info["muted_until"]), "message_id": None}
    text, kb = page_card(v)
    res = call("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
                               "disable_notification": not loud, "reply_markup": kb})
    mid = ((res.get("result") or {}).get("message_id")) if res.get("ok") else None
    g = gclient.engine().select_graph(graph)
    for pid in pids:
        writes.record_page_message(g, pid=pid, chat=str(chat) if mid else None, mid=mid, digest=digest(text, kb) if mid else "")
    return {"ok": bool(res.get("ok")), "chat": "linked" if info else "shared", "message_id": mid,
            **({} if res.get("ok") else {"error": res.get("description")})}


def refresh_incident(tenant: str, graph: str, inc: str) -> int:
    """Re-render every Telegram card of an incident and edit the ones whose content changed (an edit makes no sound,
    and an unchanged card is never re-sent). Pages that share one message (a coalesced wave) are one card: rendered
    together, edited once. Returns how many messages were edited."""
    if not configured():
        return 0
    n = 0
    # Q-PAGE-TG: internal (Telegram chat ids never reach an API or MCP reader)
    rows = RO(tenant, graph).run("Q-PAGE-TG", {"inc": inc}).rows
    groups: dict[tuple[str, int], list[dict]] = {}
    for p in rows:
        if p.get("tg_message_id") and p.get("tg_chat"):
            groups.setdefault((str(p["tg_chat"]), int(p["tg_message_id"])), []).append(p)
    for (chat, mid), ps in groups.items():
        v = wave_view(tenant, graph, [p["id"] for p in ps], chat_person=chat_person(tenant, chat) if len(ps) > 1 else None)
        if v is None:
            continue
        text, kb = page_card(v)
        d = digest(text, kb)
        if all(d == p.get("tg_digest") for p in ps):
            continue
        res = call("editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML",
                                       "disable_web_page_preview": True, "reply_markup": kb})
        if res.get("ok") or "not modified" in str(res.get("description") or ""):
            g = gclient.engine().select_graph(graph)
            for p in ps:
                writes.record_page_message(g, pid=p["id"], chat=None, mid=None, digest=d)
            n += 1
    return n


__all__ = ["call", "configured", "esc", "fit", "split", "page_card", "wave_card", "page_view", "wave_view",
           "incident_facts", "send_page", "send_group", "group_by_chat", "chat_person", "send_text", "refresh_incident",
           "COMMANDS", "DESCRIPTION", "SHORT_DESCRIPTION", "scrub", "cb", "LIMIT", "SAFE"]
