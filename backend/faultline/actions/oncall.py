"""On-call (M19): who is paged, how they acknowledge, how an unacknowledged page escalates, the shift report and the
on-call numbers. Pages, acks and the escalation order are FalkorDB nodes and edges (graph/writes.py, one atomic query
each); every decision reads a template (graph/templates/*.cypher) through the RO wrapper:

* who is paged: the on-call person of the team that owns the failing component (who_fixes, Q-ORG-WHO) and of every
  team that owns something in its blast radius (notify_set, Q-NOTIFY-1); urgency from the obligation clock;
* who is next when nobody acknowledges: the incident's escalation order (algo.MSF tree, ranked in Cypher on write,
  read by Q-PAGE-NEXT); what is overdue: Q-PAGE-OVERDUE; windows from weights.yaml `oncall`;
* who may approve: Q-APPROVER-1 (on call for, or member of, a team that owns an impacted component);
* the shift report and the stats: Q-SHIFT-REPORT and Q-ONCALL-STATS per graph (the tenant graph and the run graphs it
  indexes), merged here (lists concatenated, counts and sums added; nothing is computed outside Cypher but the sums).

The page/ack/report/contract design is adapted from the author's Beacon project (channels, approvals, reports).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from ..agent.weights import weights
from ..config import settings
from ..graph import client as gclient
from ..graph import writes
from ..graph.errors import GraphNotReady
from ..graph.ro import RO
from ..graph.tenant import audit_graph, check_tenant, golden_graph, graph_belongs_to, oncall_graph
from . import channels

log = logging.getLogger("faultline.oncall")

SETTLED = ("RESOLVED", "NO_INCIDENT")   # an incident in these stages never escalates again
_EPHEMERAL_KEY = secrets.token_bytes(32)
_warned = [False]
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="faultline-deliver")
_tick_lock = threading.Lock()
_home_lock = threading.Lock()
_homes: set[str] = set()
ASYNC = True   # deliveries and Telegram card refreshes run in the background (tests set False to run them inline)
_queue = threading.BoundedSemaphore(int(weights()["oncall"]["delivery_queue"]))   # a bounded delivery backlog


def _submit(fn, *args, **kwargs) -> bool:
    """Run `fn` in the background pool, or refuse (False) when weights.yaml oncall.delivery_queue jobs already wait:
    a burst can never queue unbounded work. Inline when ASYNC is off (tests)."""
    if not ASYNC:
        fn(*args, **kwargs)
        return True
    if not _queue.acquire(blocking=False):
        log.error("delivery queue full: %s dropped (the page stays in-app)", getattr(fn, "__name__", "job"))
        return False

    def run() -> None:
        try:
            fn(*args, **kwargs)
        finally:
            _queue.release()
    _pool.submit(run)
    return True


def now_ms() -> int:
    return int(time.time() * 1000)


def _each(tenant: str, graphs: Iterable[str] | None):
    """(graph, RO) for every graph to read; a graph that vanished meanwhile (collected run graph) is skipped and
    logged. An unavailable engine still raises (fail loudly)."""
    for graph in (list(graphs) if graphs is not None else tenant_graphs(tenant)):
        yield graph, RO(tenant, graph)


# ------------------------------------------------------------------ windows, ids, tokens, links
def urgency_of(urgent: bool | None) -> str:
    """The obligation clock's verdict as a page urgency. Unknown (None: every SLO unmeasured, or the clock failed) is
    paged as urgent: an unmeasured promise is never read as safe."""
    return "normal" if urgent is False else "urgent"


def ack_window_ms(urgency: str) -> int:
    w = weights()["oncall"]
    if settings.faultline_oncall_demo_windows:
        return int(w["demo_ack_window_s"]) * 1000
    return int(w["ack_window_min"]["urgent" if urgency == "urgent" else "normal"]) * 60_000


def page_id(graph: str, inc: str, person: str, kind: str, attempt: int) -> str:
    """Deterministic: a retried run never pages the same person twice for the same step."""
    return "pg-" + hashlib.sha256(f"{graph}|{inc}|{person}|{kind}|{attempt}".encode()).hexdigest()[:14]


def _key() -> bytes:
    if settings.faultline_page_secret:
        return settings.faultline_page_secret.encode()
    if not _warned[0]:
        log.warning("FAULTLINE_PAGE_SECRET is not set: page ack tokens use a random per-process key and stop working "
                    "after a restart")
        _warned[0] = True
    return _EPHEMERAL_KEY


def _mac(tenant: str, pid: str, exp: int) -> str:
    mac = hmac.new(_key(), f"faultline-page|{check_tenant(tenant)}|{pid}|{int(exp)}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")


def page_token(tenant: str, pid: str, now: int | None = None) -> str:
    """The signed per-page ack token: HMAC-SHA256 over tenant, page id and an expiry (weights.yaml
    oncall.ack_token_ttl_h), as `<expiry base36>.<mac>`. It only acknowledges this one page, until it expires."""
    exp = (now_ms() if now is None else int(now)) + int(weights()["oncall"]["ack_token_ttl_h"]) * 3_600_000
    return f"{_b36(exp)}.{_mac(tenant, pid, exp)}"


def _b36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


def token_ok(tenant: str, pid: str, token: str | None, now: int | None = None) -> bool:
    if not token or "." not in str(token):
        return False
    exp_s, _, mac = str(token).partition(".")
    try:
        exp = int(exp_s, 36)
    except ValueError:
        return False
    if exp < (now_ms() if now is None else int(now)):
        return False
    return hmac.compare_digest(_mac(tenant, pid, exp).encode(), mac.encode())


def page_path(tenant: str, pid: str) -> str:
    return f"{settings.faultline_public_url.rstrip('/')}/oncall/page/{pid}?tenant={tenant}"


def deep_link(tenant: str, pid: str, issued_at: int | None = None) -> str:
    """The phone link a channel delivers: it carries the page's ack token (never stored in the graph). `issued_at`
    (the page's sent_at) fixes the token's expiry, so the same page always renders the same link (a Telegram card is
    edited only when something real changed)."""
    return f"{page_path(tenant, pid)}&t={page_token(tenant, pid, now=issued_at)}"


def token_policy() -> str:
    return "signed (FAULTLINE_PAGE_SECRET)" if settings.faultline_page_secret else "ephemeral (per-process key; set FAULTLINE_PAGE_SECRET)"


# ------------------------------------------------------------------ which graphs hold on-call state
def home_graph(tenant: str) -> str:
    """The tenant's durable on-call graph (oncall_<t>): alert-intake incidents and their pages, standing contracts,
    hand-offs, the Telegram bot's state, the delivery budget and the index of graphs holding pages. Made once as a
    copy of golden_<t> (people, rota, components); re-arm and seeding swap the TENANT graph and never touch it."""
    from ..graph import copy as gcopy

    t = check_tenant(tenant)
    name = oncall_graph(t)
    if name in _homes:
        return name
    with _home_lock:
        db = gclient.engine()
        if not gcopy.exists(db, name):
            gcopy.copy_graph(db, golden_graph(t), name)   # the schema is applied after the copy
            log.warning("created the on-call graph %s from %s", name, golden_graph(t))
        _homes.add(name)
    return name


MAX_PAGE_GRAPH_PAGES = 50   # × 100 graphs per Q-PAGE-GRAPHS page


def tenant_graphs(tenant: str) -> list[str]:
    """The graphs that hold on-call state of a tenant: its on-call graph, then every graph the durable index says holds
    pages (Q-PAGE-GRAPHS, keyset-paged: no list cap decides what escalates) that still exists. Pages live with their
    incident (Page -[:FOR]-> Incident is one graph's edge)."""
    t = check_tenant(tenant)
    home = home_graph(t)
    names = set(gclient.engine().list_graphs())
    out, after, gone = [home], "", []
    ro = RO(t, home)
    for _ in range(MAX_PAGE_GRAPH_PAGES):
        page = ro.run("Q-PAGE-GRAPHS", {"after": after})
        for r in page.rows:
            g = r["graph"]
            if g in names and graph_belongs_to(g, t):
                if g not in out:
                    out.append(g)
            elif g != home:
                gone.append(g)
        if not page.truncated:
            break
        after = page.rows[-1]["graph"]
    else:
        log.error("Q-PAGE-GRAPHS: more than %d pages of page-holding graphs; the rest wait for the next pass",
                  MAX_PAGE_GRAPH_PAGES)
    if gone:   # collected run graphs leave the index (their pages went with them)
        writes.drop_page_graphs(gclient.engine().select_graph(home), graphs=gone)
    return out


def index_graph(tenant: str, graph: str, now: int | None = None) -> None:
    """Record that `graph` holds pages (escalation and the pager read every such graph)."""
    home = home_graph(tenant)
    if graph != home:
        writes.index_page_graph(gclient.engine().select_graph(home), graph=graph, tenant=tenant,
                                now=now_ms() if now is None else int(now))


# ------------------------------------------------------------------ who is paged (from the ROUTE graph tools)
def recipients(who: dict | None, notify: dict | None, target: str | None,
               learned: list[dict] | None = None) -> list[dict]:
    """The people to page, in order: the owner team's on-call for the failing component (who_fixes → Q-ORG-WHO's
    on-call column), then the on-call of every team that owns something in the blast radius (notify_set → Q-NOTIFY-1),
    as those tools ranked them. One page per person (a person on call for two teams is paged once, for the first).
    `learned` (M21, memory/learning.first_wave: who actually answers this component's pages, Q-LEARN-RESP) go FIRST;
    they are added, never instead of anyone the rota pages."""
    out: list[dict] = []
    seen: set[str] = set()
    for p in learned or []:
        if p["person"] not in seen:
            seen.add(p["person"])
            out.append({"person": p["person"], "team": p.get("team") or "", "reason": p["reason"],
                        "evidence": p.get("evidence") or "", "learned": True})
    who = who or {}
    for pid in who.get("oncall_now") or []:
        if pid not in seen:
            seen.add(pid)
            out.append({"person": pid, "team": who.get("owner_team") or "",
                        "reason": f"on call for {who.get('owner_team') or 'the owner team'}, which owns {target} "
                                  "(the failing component)", "evidence": who.get("evidence_id") or ""})
    for row in (notify or {}).get("rows") or []:
        for pid in row.get("oncall") or []:
            if pid not in seen:
                seen.add(pid)
                owns = ", ".join((row.get("owns_impacted") or [])[:4])
                out.append({"person": pid, "team": row.get("team") or "",
                            "reason": f"on call for {row.get('name') or row.get('team')}, which owns {owns} in the blast "
                                      f"radius of {target}", "evidence": (notify or {}).get("evidence_id") or ""})
    return out


def write_pages(*, tenant: str, graph: str, inc: str, people: list[dict], kind: str, urgency: str, title: str,
                detail: str, now: int | None = None, attempt: int = 1, wait: bool = False,
                key: str | None = None) -> list[str]:
    """Page every person (one atomic write for the incident), then deliver on the configured channels in the
    background (the result is written back on each Page). contract_notice pages inform; they never escalate.
    `key` (default: the kind) goes into each page id: the same key for the same person and incident is the same page,
    so writing it again (a reconciler settling the same outcome) creates and delivers nothing new."""
    now = now_ms() if now is None else int(now)
    # a contract notice carries a deadline too: if its fix never settles (a crash between the match and the action),
    # the tick pages its people (tick → contract_deadline)
    window = ack_window_ms(urgency) if kind in ("page", "escalation", "contract_notice") else 0
    index_graph(tenant, graph, now)
    rows = []
    for p in people:
        pid = page_id(graph, inc, p["person"], key or kind, attempt)
        rows.append({"id": pid, "person": p["person"], "kind": kind, "urgency": urgency, "window_ms": window,
                     "attempt": attempt, "detail": detail, "deep_link": page_path(tenant, pid), "team": p.get("team"),
                     "reason": p.get("reason"), "evidence": p.get("evidence")})
    made = writes.create_pages(gclient.engine().select_graph(graph), tenant=tenant, inc=inc, pages=rows, now=now)
    ids = [m["id"] for m in made]
    fresh = {m["id"] for m in made if m["fresh"]}
    # ONE wave: everyone this call paged about this incident is told in one message per destination (coalesced: a
    # shared chat or the operator's inbox gets one card / one email, not one per person); the Pages stay per person
    wave = [{"id": r["id"], "person": r["person"], "reason": r.get("reason") or ""} for r in rows if r["id"] in fresh]
    if wave:
        deliver_wave(tenant=tenant, graph=graph, inc=inc, pages=wave, kind=kind, title=title, detail=detail,
                     note=(f" Acknowledge within {window // 60_000 or 1} min or it escalates." if window else ""),
                     wait=wait)
    return ids


def external_allowed(tenant: str, graph: str, pid: str) -> tuple[bool, str, str | None]:
    """May this page leave the in-app pager? Only for a trusted incident: one in the on-call graph (a keyed alert),
    or one whose run was started off the public demo or with the approver key (Incident.page_external). An anonymous
    demo run pages in-app only. Returns (allowed, why, the paged person)."""
    row = (RO(tenant, graph).run("Q-PAGE-ONE", {"page": pid, "now": now_ms()}).rows or [{}])[0]
    if graph == home_graph(tenant):
        return True, "on-call graph", row.get("person")
    if row.get("external"):
        return True, "trusted run", row.get("person")
    return False, "in-app only: an anonymous demo run (external channels need a keyed alert or a keyed run)", row.get("person")


def _budgeted(tenant: str, channel: str, people: str | list[str] | None, now: int) -> str | None:
    """None when `channel` may send one more MESSAGE now; else why not. Decided once per combined message (a coalesced
    wave is one message): the per-recipient cooldown passes when at least one person the message is for was not
    buzzed on this channel in the last weights.yaml oncall.recipient_cooldown_s (each person's own counter, as before
    coalescing), and the hourly budget takes ONE unit per message. Counters live in the on-call graph."""
    w = weights()["oncall"]
    g = gclient.engine().select_graph(home_graph(tenant))
    people = [people] if isinstance(people, str) else [x for x in (people or []) if x]
    if people:
        passed = [x for x in dict.fromkeys(people)
                  if writes.take_recipient_cooldown(g, channel=channel, recipient=x,
                                                    cooldown_ms=int(w["recipient_cooldown_s"]) * 1000, now=now)]
        if not passed:
            return (f"budget: {', '.join(people[:3])}{'…' if len(people) > 3 else ''} paged on {channel} less than "
                    f"{int(w['recipient_cooldown_s'])} s ago")
    cap = int((w["delivery_per_hour"] or {}).get(channel, 0))
    if not writes.take_delivery_budget(g, channel=channel, hour=now // 3_600_000, cap=cap, now=now):
        return f"budget: {channel} sent its {cap} messages this hour"
    return None


def deliver(*, tenant: str, graph: str, pid: str, kind: str, inc: str | None, title: str, text: str,
            wait: bool = False) -> None:
    """One page on its own (an escalation step, a hand-off report): a wave of one."""
    deliver_wave(tenant=tenant, graph=graph, inc=inc, pages=[{"id": pid, "person": None, "reason": ""}], kind=kind,
                 title=title, detail=text, note="", wait=wait)


def wave_id(graph: str, inc: str | None, pids: list[str]) -> str:
    """The id of one delivery wave (the pages one write made for one incident): what each Page says it was coalesced
    into, the same for every page of the wave."""
    return "wv-" + hashlib.sha256(f"{graph}|{inc}|{'|'.join(sorted(pids))}".encode()).hexdigest()[:12]


def _wave_text(tenant: str, pages: list[dict], detail: str, note: str) -> str:
    """The text of a combined message (webhook, email, PagerDuty): the incident line once, then everyone paged with
    their reason and their OWN signed ack link (each acknowledges their own page)."""
    if len(pages) == 1:
        p = pages[0]
        return (f"{p['reason']}. " if p.get("reason") else "") + detail + note
    lines = [detail.strip(), "", f"Paged ({len(pages)}), one message for everyone this incident paged; each person "
                                 "acknowledges their own page:"]
    for p in pages:
        name = p.get("name") or p.get("person")
        link = deep_link(tenant, p["id"], issued_at=p.get("sent_at")) if p.get("sent_at") is not None else deep_link(tenant, p["id"])
        lines.append(f"- {name} ({p.get('person')}): {p.get('reason') or ''}. Acknowledge: {link}")
    return "\n".join(lines) + ("\n" + note.strip() if note else "")


def deliver_wave(*, tenant: str, graph: str, inc: str | None, pages: list[dict], kind: str, title: str, detail: str,
                 note: str = "", wait: bool = False) -> None:
    """External delivery of one WAVE (the pages one write made for one incident), never blocking a run; the in-app
    Pages exist either way. Coalesced per destination: pages whose people resolve to the same Telegram chat become ONE
    card listing everyone paged (actions/telegram.send_group; edited in place later), and the webhook, PagerDuty and
    the SES inbox get ONE message for the wave with each person's signed ack link. Only for a trusted incident; the
    hourly budget counts combined messages (one per destination), not pages, and the cooldown is decided once per
    message. Each Page
    records its delivery, with `coalesced_into` and `pages` when it shared a message. The cooldown still keeps each
    person to one buzz per channel per oncall.recipient_cooldown_s: a message is held back only when every person it
    is for was buzzed that recently (an escalation to someone new always goes out)."""
    ext = channels.external()
    if not ext or not pages:
        return
    pids = [p["id"] for p in pages]

    def job() -> None:
        g = gclient.engine().select_graph(graph)
        try:
            now = now_ms()
            ok, why, _person = external_allowed(tenant, graph, pids[0])
            if not ok:
                for pid in pids:
                    writes.record_delivery(g, pid=pid, delivery={"in_app": {"ok": True}, "external": {"ok": None, "note": why}},
                                           now=now)
                return
            wave = wave_id(graph, inc, pids)
            res: dict[str, dict] = {pid: {"in_app": {"ok": True}} for pid in pids}
            rows = {r["id"]: r for r in RO(tenant, graph).run("Q-PAGES", {"incident": inc or "", "statuses": [],
                                                                          "now": now}).rows} if inc else {}
            full = [{**p, "name": (rows.get(p["id"]) or {}).get("person_name"),
                     "person": p.get("person") or (rows.get(p["id"]) or {}).get("person")
                     or (_person if len(pages) == 1 else None),
                     "sent_at": (rows.get(p["id"]) or {}).get("sent_at")} for p in pages]
            # webhook, PagerDuty, email: one message per destination for the whole wave
            others = [ch for ch in ext if ch != "telegram"]
            if others:
                everyone = [p["person"] for p in full]
                refused = {ch: r for ch in others for r in [_budgeted(tenant, ch, everyone, now)] if r}
                single = len(pages) == 1
                link = deep_link(tenant, pids[0]) if single else \
                    (f"{settings.faultline_public_url.rstrip('/')}/incidents/{inc}?tenant={tenant}" if inc else "")
                sent = channels.send(kind, title, _wave_text(tenant, full, detail, note), tenant=tenant, incident=inc,
                                     page_id=pids[0] if single else None, link=link, skip=("telegram", *refused))
                for ch, r in sent.items():
                    if ch == "in_app":
                        continue
                    for pid in pids:
                        res[pid][ch] = {**r, "pages": len(pids)} | ({} if single else {"coalesced_into": f"{ch} {wave}"})
                for ch, r in refused.items():
                    for pid in pids:
                        res[pid][ch] = {"ok": False, "error": r, "pages": len(pids)}
            # Telegram: one card per chat (a person's own linked chat, else the shared on-call chat)
            if "telegram" in ext:
                from . import telegram

                who = {p["id"]: p["person"] for p in full}
                for chat, info, group in telegram.group_by_chat(tenant, graph, pids):
                    if not chat:
                        for pid in group:
                            res[pid]["telegram"] = {"ok": False, "error": "no Telegram chat (/start the bot, or set "
                                                                         "TELEGRAM_CHAT_ID)"}
                        continue
                    r = _budgeted(tenant, "telegram", [who.get(pid) for pid in group], now)
                    out = {"ok": False, "error": r} if r else telegram.send_group(tenant, graph, chat, info, group)
                    for pid in group:
                        res[pid]["telegram"] = {**out, "pages": len(group)} | (
                            {"coalesced_into": f"telegram message {out.get('message_id')}"}
                            if len(group) > 1 and out.get("message_id") else {})
            for pid in pids:
                writes.record_delivery(g, pid=pid, delivery=res[pid], now=now)
        except Exception as e:  # noqa: BLE001 - delivery is best effort; the pages and their escalation stand
            log.error("delivery of %s (%d page(s)) failed: %s", pids[0], len(pids), type(e).__name__)
    if wait or not ASYNC:
        job()
    elif not _submit(job):
        try:
            for pid in pids:
                writes.record_delivery(gclient.engine().select_graph(graph), pid=pid,
                                       delivery={"in_app": {"ok": True}, **{ch: {"ok": False, "error": "delivery queue full"}
                                                                            for ch in ext}}, now=now_ms())
        except Exception as e:  # noqa: BLE001
            log.error("recording the queue-full delivery of %s failed: %s", pids[0], type(e).__name__)


def touch(tenant: str, graph: str, inc: str | None) -> None:
    """The incident changed (acked, escalated, approved, resolved…): edit its Telegram cards in place. Best effort."""
    from . import telegram

    if not inc or not telegram.configured():
        return

    def job() -> None:
        try:
            telegram.refresh_incident(tenant, graph, inc)
        except Exception as e:  # noqa: BLE001 - a stale card is visible, never a failure of the change itself
            log.warning("refreshing the Telegram cards of %s failed: %s", inc, type(e).__name__)
    _submit(job)


def locate_incident(tenant: str, inc: str) -> dict | None:
    """Which graph and run hold an incident (the audit index, Q-RUNS-2), when that graph still exists."""
    t = check_tenant(tenant)
    try:
        rows = RO(t, audit_graph(t)).run("Q-RUNS-2", {"inc": inc}).rows
    except GraphNotReady:
        return None
    if not rows or not rows[0].get("graph") or not graph_belongs_to(rows[0]["graph"], t):
        return None
    return rows[0] if rows[0]["graph"] in set(gclient.engine().list_graphs()) else None


# ------------------------------------------------------------------ escalation
def tick(tenant: str, graphs: Iterable[str] | None = None, now: int | None = None, wait: bool = False) -> list[dict]:
    """One escalation pass: in every graph, the pages nobody acknowledged in time (Q-PAGE-OVERDUE) escalate, per
    incident, to the next person of its escalation order (Q-PAGE-NEXT) in ONE write (W_PAGE_ESCALATE); with nobody
    left, or past weights.yaml oncall.max_escalations, the pages are marked exhausted for a human. Serialised in this
    process; the write re-checks every condition, so two ticks never escalate the same page twice."""
    t = check_tenant(tenant)
    now = now_ms() if now is None else int(now)
    max_esc = int(weights()["oncall"]["max_escalations"])
    out: list[dict] = []
    with _tick_lock:
        for graph, ro in _each(t, graphs):
            try:
                rows = ro.run("Q-PAGE-OVERDUE", {"now": now, "settled": list(SETTLED)}).rows
            except GraphNotReady:
                log.info("escalation tick: %s is gone (collected); skipped", graph)
                continue
            by_inc: dict[str, list[dict]] = {}
            for r in rows:
                by_inc.setdefault(r["incident"], []).append(r)
            for inc, pages in by_inc.items():
                notices = [p for p in pages if p.get("kind") == "contract_notice"]
                if notices:
                    out += contract_deadline(t, graph, inc, notices, now=now)
                pages = [p for p in pages if p.get("kind") != "contract_notice"]
                if not pages:
                    continue
                overdue = [p["page"] for p in pages]
                attempt = max(int(p["attempt"] or 1) for p in pages) + 1
                urgency = "urgent" if any(p["urgency"] == "urgent" for p in pages) else "normal"
                nxt = ro.run("Q-PAGE-NEXT", {"inc": inc}).rows if attempt <= max_esc + 1 else []
                g = gclient.engine().select_graph(graph)
                if not nxt:
                    res = writes.escalate_pages(g, tenant=t, inc=inc, overdue=overdue, page=None, now=now)
                    if res:
                        out.append({"graph": graph, "incident": inc, "escalated": overdue, "to": None,
                                    "why": "escalation order exhausted"})
                    continue
                n = nxt[0]
                pid = page_id(graph, inc, n["person"], "escalation", attempt)
                who = ", ".join(sorted({p["person"] for p in pages}))
                detail = (f"Nobody acknowledged the page to {who} within its window: escalated to you (escalation order "
                          f"rank {n['rank']}, {n['via']}).")
                res = writes.escalate_pages(g, tenant=t, inc=inc, overdue=overdue, now=now, page={
                    "id": pid, "person": n["person"], "urgency": urgency, "window_ms": ack_window_ms(urgency),
                    "attempt": attempt, "detail": detail, "deep_link": page_path(t, pid),
                    "reason": f"escalation step {attempt - 1}: {n['via']} rank {n['rank']}"})
                if res and res.get("page"):
                    out.append({"graph": graph, "incident": inc, "escalated": overdue, "to": n["person"], "page": pid,
                                "attempt": attempt})
                    deliver(tenant=t, graph=graph, pid=pid, kind="escalation", inc=inc, title=f"Escalated: {inc}",
                            text=detail, wait=wait)
                    touch(t, graph, inc)
    return out


def contract_deadline(tenant: str, graph: str, inc: str, notices: list[dict], now: int | None = None) -> list[dict]:
    """A standing contract's fix did not settle within the notice's window (a crash between the match and the action,
    or a stuck job): the people it informed are paged now, urgently, and the notices superseded. Idempotent (one key
    per incident)."""
    now = now_ms() if now is None else int(now)
    writes.settle_pages(gclient.engine().select_graph(graph), inc=inc, status="superseded", now=now,
                        detail="superseded: the standing contract's fix did not settle in time", kinds=("contract_notice",))
    people = [{"person": p["person"], "team": "", "evidence": "",
               "reason": "you were told a standing contract would fix this; it did not settle in time"}
              for p in {n["person"]: n for n in notices}.values()]
    ids = write_pages(tenant=tenant, graph=graph, inc=inc, people=people, kind="page", urgency="urgent",
                      title=f"{inc}: the contract fix did not settle", now=now, key=f"contract-deadline|{inc}",
                      detail="A standing contract matched this incident, but no verified APPLIED fix followed within the "
                             "window (the action may have crashed or be stuck). A human must look now.")
    touch(tenant, graph, inc)
    return [{"graph": graph, "incident": inc, "escalated": [n["page"] for n in notices], "to": p["person"], "page": pid,
             "why": "contract deadline"} for p, pid in zip(people, ids)]


def escalate_now(tenant: str, graph: str, inc: str, by: str, now: int | None = None) -> dict:
    """A human asks for the next person before the deadline (Telegram's Escalate now): the incident's open pages
    escalate at once to the next person of its escalation order, in the same single write as a late escalation."""
    t = check_tenant(tenant)
    now = now_ms() if now is None else int(now)
    ro = RO(t, graph)
    open_ = [p for p in list_pages(t, statuses=["sent", "delivery_failed"], incident=inc, graphs=[graph], now=now)["rows"]
             if p["kind"] in ("page", "escalation")]
    if not open_:
        return {"escalated": [], "to": None, "why": "no open page to escalate (acknowledged, escalated or resolved)"}
    nxt = ro.run("Q-PAGE-NEXT", {"inc": inc}).rows
    if not nxt:
        return {"escalated": [], "to": None, "why": "nobody left in the escalation order"}
    n = nxt[0]
    attempt = max(int(p["attempt"] or 1) for p in open_) + 1
    urgency = "urgent" if any(p["urgency"] == "urgent" for p in open_) else "normal"
    pid = page_id(graph, inc, n["person"], "escalation", attempt)
    detail = f"{by} asked to escalate now: escalated to you (escalation order rank {n['rank']}, {n['via']})."
    res = writes.escalate_pages(gclient.engine().select_graph(graph), tenant=t, inc=inc, overdue=[p["id"] for p in open_],
                                now=now, force=True, page={"id": pid, "person": n["person"], "urgency": urgency,
                                                           "window_ms": ack_window_ms(urgency), "attempt": attempt,
                                                           "detail": detail, "deep_link": page_path(t, pid),
                                                           "reason": f"escalated now by {by}: {n['via']} rank {n['rank']}"})
    if not res or not res.get("page"):
        return {"escalated": [], "to": None, "why": "the incident was acknowledged meanwhile"}
    deliver(tenant=t, graph=graph, pid=pid, kind="escalation", inc=inc, title=f"Escalated: {inc}", text=detail)
    touch(t, graph, inc)
    return {"escalated": [p["id"] for p in open_], "to": n["person"], "to_name": n["name"], "page": pid}


def locate_page(tenant: str, pid: str, graphs: Iterable[str] | None = None) -> tuple[str, dict] | None:
    """Which graph holds a page (Q-PAGE-ONE in each of the tenant's graphs, newest runs first)."""
    t = check_tenant(tenant)
    for graph, ro in _each(t, graphs):
        try:
            rows = ro.run("Q-PAGE-ONE", {"page": pid, "now": now_ms()}).rows
        except GraphNotReady:
            continue
        if rows:
            return graph, rows[0]
    return None


def ack_anonymous(tenant: str, graph: str, pid: str, via: str, actor: str, now: int | None = None) -> dict | None:
    """An acknowledgement by someone who is not a person of the graph (the holder of a demo run's token): recorded as
    who acted, never as the paged person, and left out of MTTA."""
    res = writes.ack_page_anonymous(gclient.engine().select_graph(graph), pid=pid, via=via, actor=actor,
                                    now=now_ms() if now is None else int(now))
    if res:
        touch(tenant, graph, res.get("incident"))
    return res


def ack(tenant: str, graph: str, pid: str, by: str, via: str, now: int | None = None,
        tg_user: str | None = None) -> dict | None:
    res = writes.ack_page(gclient.engine().select_graph(graph), pid=pid, by=by, via=via,
                          now=now_ms() if now is None else int(now), tg_user=tg_user)
    if res:
        touch(tenant, graph, res.get("incident"))
    return res


AFTER_APPROVAL_DONE = ("RESOLVED",)


def page_after_approval(tenant: str, graph: str, inc: str, run: str, aid: str, now: int | None = None) -> dict | None:
    """An APPROVED action ended without a verified, resolved fix: page a human at once, urgent. Read from the graph
    (Q-ACT-APPROVER, Q-RUN-1): verification UNKNOWN, the write-back not fully re-read, an issue handed to humans
    (UNKNOWN_ESCALATED), NOT_APPLIED (back to AWAITING_APPROVAL), or not executed (FAILED). Who: everyone already paged
    or notified about the incident, plus the approver when they are a person (a standing contract is not); with
    nobody, the first of the escalation order. Idempotent per incident, action and outcome (the page ids carry the
    outcome), so the execute job and a reconciler settling the same outcome page once. A RESOLVED outcome instead
    resolves the open pages. Returns what it did, or None when there is nothing to page (still in progress)."""
    now = now_ms() if now is None else int(now)
    ro = RO(check_tenant(tenant), graph)
    rows = ro.run("Q-ACT-APPROVER", {"inc": inc, "aid": aid}).rows
    if not rows:
        return None
    a = rows[0]
    stage, verdict = a["stage"], a["verdict"]
    if stage in AFTER_APPROVAL_DONE:
        settle_resolved(tenant, graph, inc, now)
        return {"resolved": True}
    stages = ro.run("Q-RUN-1", {"run": run}).rows
    note = (stages[-1].get("note") if stages else "") or ""
    approver = str(a["approver"] or "")
    by = f"standing contract {approver.removeprefix('contract:')}" if approver.startswith("contract:") else approver
    explanation = (a.get("explanation") or note or "")[:300]
    if stage == "UNKNOWN_ESCALATED":
        what = ("verification UNKNOWN" if verdict == "UNKNOWN" else
                "handed to humans (an issue tracks it; nothing changed in production)" if a["kind"] == "open_issue"
                and verdict == "APPLIED" else
                "write-back not fully verified" if verdict == "APPLIED" else "escalated")
    elif stage == "AWAITING_APPROVAL" and verdict == "NOT_APPLIED":
        what = "the fix did NOT apply (NOT_APPLIED); the option is disabled, choose another"
    elif stage == "FAILED":
        what = "not executed"
    else:
        return None
    detail = (f"{what[0].upper() + what[1:]} after approval by {by}: {explanation or note[:300]}. "
              "A human must decide now.").replace("..", ".")
    people: list[dict] = []
    seen: set[str] = set()
    for p in list_pages(tenant, incident=inc, graphs=[graph], now=now)["rows"]:
        pid = (p.get("person") or {}).get("id")
        if pid and pid not in seen and p.get("kind") in ("page", "escalation", "contract_notice"):
            seen.add(pid)
            people.append({"person": pid, "team": p.get("team") or "", "evidence": "",
                           "reason": f"paged about {inc} before; {what} after approval"})
    if approver and not approver.startswith("contract:") and approver not in seen \
            and ro.run("Q-PERSON-1", {"person": approver}).rows:
        people.append({"person": approver, "team": "", "evidence": "", "reason": f"approved {aid}; {what}"})
    if not people:
        nxt = ro.run("Q-PAGE-NEXT", {"inc": inc}).rows
        people = [{"person": nxt[0]["person"], "team": "", "evidence": "",
                   "reason": f"first of the escalation order ({nxt[0]['via']}); {what} after approval"}] if nxt else []
    if not people:
        log.error("%s/%s: %s after approval, and nobody could be paged (no page, no escalation order)", inc, aid, what)
        return {"pages": [], "what": what, "why": "nobody to page"}
    key = f"after-approval|{aid}|{stage}|{verdict}"
    ids = write_pages(tenant=tenant, graph=graph, inc=inc, people=people, kind="page", urgency="urgent",
                      title=f"{inc}: {what.split(' (')[0]} after approval", detail=detail, now=now, key=key)
    touch(tenant, graph, inc)
    return {"pages": ids, "what": what, "key": key, "people": [p["person"] for p in people]}


def hand_off(tenant: str, *, from_: str | None, to: str, note: str, inc: str = "", now: int | None = None) -> dict:
    """Hand the shift over (POST /api/handoffs and the bot's /handoff): (:Handoff)-[:FROM]->(outgoing), -[:TO]->
    (incoming), -[:COVERS]->(incident) in the on-call home graph, and a report page to the incoming person. `from_`
    None: whoever is on call now for the incoming person's team (Q-HANDOFF-FROM). ValueError with the reason when a
    person is unknown or inactive."""
    t = check_tenant(tenant)
    home = home_graph(t)
    now = now_ms() if now is None else int(now)
    ro = RO(t, home)
    note = note.strip()
    if not ro.run("Q-PERSON-1", {"person": to}).rows:
        raise ValueError(f"{to!r} is not an active person in this tenant's graph")
    shift = ""
    if not from_:
        rows = ro.run("Q-HANDOFF-FROM", {"to": to, "now": now}).rows
        if not rows:
            raise ValueError("nobody else is on call for the incoming person's team now: name `from`")
        from_, shift = rows[0]["person"], f"{rows[0]['team']} {rows[0]['from']}..{rows[0]['to']}"
    elif not ro.run("Q-PERSON-1", {"person": from_}).rows:
        raise ValueError(f"{from_!r} is not an active person in this tenant's graph")
    hid = "ho-" + secrets.token_hex(7)
    g = gclient.engine().select_graph(home)
    res = writes.hand_off_shift(g, hid=hid, tenant=t, from_=from_, to=to, note=note, from_shift=shift, inc=inc or "",
                                now=now)
    if res is None:
        raise ValueError("hand-off refused: a person is unknown or inactive")
    pid = "pg-" + hashlib.sha256(f"{home}|{hid}".encode()).hexdigest()[:14]
    writes.create_note_page(g, tenant=t, pid=pid, person=to, kind="report", detail=note, reason=f"hand-off from {from_}",
                            now=now, inc=inc or "", deep_link=page_path(t, pid))
    deliver(tenant=t, graph=home, pid=pid, kind="report", inc=inc or None, title=f"Hand-off from {from_}", text=note)
    return {"id": res["id"], "at": res["at"], "from": from_, "to": to, "incident": inc or None, "page": pid}


def on_approval(tenant: str, graph: str, inc: str, approver: str, now: int | None = None) -> dict | None:
    """A human approved a fix: that is the acknowledgement. Their own open page is acked (via "approval", which
    supersedes the incident's other open pages in the same write); if they were not paged, the open pages are
    superseded. Either way the escalation stops."""
    now = now_ms() if now is None else int(now)
    mine = [p for p in list_pages(tenant, statuses=["sent", "delivery_failed"], incident=inc, graphs=[graph], now=now)["rows"]
            if p["person"]["id"] == approver and p["kind"] in ("page", "escalation")]
    if mine:
        return ack(tenant, graph, mine[0]["id"], approver, "approval", now)
    ids = writes.settle_pages(gclient.engine().select_graph(graph), inc=inc, status="superseded",
                              detail=f"approved by {approver} (not paged): escalation stopped", now=now,
                              kinds=("page", "escalation"))
    touch(tenant, graph, inc)
    return {"superseded": ids} if ids else None


def settle_resolved(tenant: str, graph: str, inc: str, now: int | None = None) -> list[str]:
    """The incident resolved: its open pages read resolved, and PagerDuty (if configured) is told to resolve."""
    ids = writes.settle_pages(gclient.engine().select_graph(graph), inc=inc, status="resolved",
                              detail="the incident resolved (verified APPLIED, write-back re-read)",
                              now=now_ms() if now is None else int(now))
    if channels.external():
        _submit(channels.send, "resolved", f"Resolved: {inc}", "verified APPLIED; write-back re-read", tenant=tenant,
                incident=inc, page_id=None, link="", skip=("telegram",))
    touch(tenant, graph, inc)
    return ids


# ------------------------------------------------------------------ who may approve (Q-APPROVER-1)
def impacted_ids(ro: RO, run: str, inc: str) -> tuple[list[str], dict]:
    """The components an incident impacts, read from the graph: its symptoms (Q-INC-1), the failing component (what
    ROUTE ran who_fixes on, else the gate-confirmed cause's target) and that component's blast radius (Q-BLAST-2)."""
    import json

    row = ro.run("Q-INC-1", {"inc": inc}).rows
    row = row[0] if row else {}
    ids = list(row.get("targets") or [])
    target = None
    ev = ro.run("Q-EV-TOOL", {"run": run, "tool": "who_fixes"}).rows
    if ev and ev[0].get("params"):  # the recorded params are the templates' (Q-ORG-WHO's `target`)
        prm = json.loads(ev[0]["params"]) or {}
        target = prm.get("target") or (prm.get("Q-ORG-WHO") or {}).get("target")
    if not target:
        cause = (ro.run("Q-CAUSE-1", {"inc": inc}).rows or [{}])[0].get("cause")
        if cause:
            target = (ro.run("Q-CHANGE-1", {"id": cause}).rows or [{}])[0].get("target")
    if target:
        ids = [target] + [r["id"] for r in ro.run("Q-BLAST-2", {"id": target}).rows] + ids
    return list(dict.fromkeys(ids)), row


def approver_check(ro: RO, *, run: str, inc: str, person: str, now: int | None = None) -> dict | None:
    """Q-APPROVER-1: may `person` approve an action on this incident? None ⇒ not an active person of this tenant
    (HTTP 422). Otherwise `eligible` (decided by the query) and the reason it states."""
    now = now_ms() if now is None else int(now)
    ids, inc_row = impacted_ids(ro, run, inc)
    since = min(int(inc_row.get("onset_at") or now), now)
    r = ro.run("Q-APPROVER-1", {"person": person, "ids": ids, "since": since, "now": now})
    if not r.rows:
        return None
    row = r.rows[0]
    oncall = sorted({tuple(x) for x in row["oncall_owns"]})
    member = sorted({tuple(x) for x in row["member_owns"]})
    if oncall:
        reason = (f"{row['name']} is on call for " + "; ".join(f"{t} (owns {c})" for t, c in oncall[:4])
                  + " during this incident")
    elif member:
        reason = f"{row['name']} is a member of " + "; ".join(f"{t}, which owns {c}" for t, c in member[:4])
    else:
        reason = (f"{row['name']} is not on call for, and not in a team that owns, any component this incident impacts "
                  f"({', '.join(ids[:6])}{'…' if len(ids) > 6 else ''})")
    return {"id": row["id"], "name": row["name"], "role": row["role"], "eligible": bool(row["eligible"]),
            "reason": reason, "oncall_for": [list(x) for x in oncall], "member_of": [list(x) for x in member],
            "impacted": ids, "template": r.template_id, "params": r.params}


# ------------------------------------------------------------------ views (the API and the MCP tools read these)
def oncall_now(tenant: str, at: int | None = None) -> dict:
    at = now_ms() if at is None else int(at)
    r = RO(check_tenant(tenant)).run("Q-ONCALL-NOW", {"now": at})
    rows = [{"team": x["team"], "team_name": x["team_name"],
             "person": {"id": x["person"], "name": x["name"]} if x["person"] else None, "from": x["from"], "to": x["to"]}
            for x in r.rows]
    return {"rows": rows, "at": at, "template": r.template_id, "params": r.params, "ms": round(r.ms, 2),
            "truncated": r.truncated, "digest": r.digest}


def page_view(x: dict) -> dict:
    """A Q-PAGES / Q-PAGE-ONE row in the API's page shape."""
    import json

    delivery = x.get("delivery")
    if isinstance(delivery, str):
        try:
            delivery = json.loads(delivery)
        except ValueError:
            delivery = None
    return {"id": x["id"], "incident": x.get("incident"), "incident_title": x.get("incident_title"),
            "incident_stage": x.get("incident_stage"), "kind": x.get("kind"), "channel": x.get("channel"),
            "channels": x.get("channels") or ["in_app"], "urgency": x.get("urgency"), "sent_at": x.get("sent_at"),
            "ack_due_at": x.get("ack_due_at"), "status": x.get("status"), "attempt": x.get("attempt"),
            "detail": x.get("detail"), "reason": x.get("reason"), "team": x.get("team"), "delivery": delivery,
            "person": {"id": x.get("person"), "name": x.get("person_name")},
            "ack": ({"by": {"id": x.get("acked_by"), "name": x.get("acked_by_name")}, "at": x.get("acked_at"),
                     "via": x.get("ack_via")} if x.get("acked_by") else
                    {"by": None, "actor": x.get("ack_actor"), "at": x.get("acked_at"), "via": x.get("ack_via")}
                    if x.get("status") == "acked" and x.get("acked_at") else None),
            "escalated_to": x.get("escalated_to"), "overdue": bool(x.get("overdue"))}


def list_pages(tenant: str, *, statuses: list[str] | None = None, incident: str = "", graphs: Iterable[str] | None = None,
               now: int | None = None) -> dict:
    t = check_tenant(tenant)
    now = now_ms() if now is None else int(now)
    rows: list[dict] = []
    queries, truncated, ms = [], False, 0.0
    for graph, ro in _each(t, graphs):
        try:
            r = ro.run("Q-PAGES", {"incident": incident or "", "statuses": list(statuses or []), "now": now})
        except GraphNotReady:
            continue
        rows += [{**page_view(x), "graph": graph} for x in r.rows]
        truncated = truncated or r.truncated
        ms += r.ms
        queries.append({"graph": graph, "rows": len(r.rows), "ms": round(r.ms, 2), "digest": r.digest})
    rows.sort(key=lambda x: (-(x.get("sent_at") or 0), x["id"]))
    return {"rows": rows[:200], "template": "Q-PAGES", "params": {"incident": incident or "", "statuses": list(statuses or []),
                                                                   "now": now},
            "ms": round(ms, 2), "truncated": truncated or len(rows) > 200, "graphs": queries}


def report(tenant: str, *, since: int, until: int, graphs: Iterable[str] | None = None) -> dict:
    """The shift (morning) report: Q-SHIFT-REPORT in every graph of the tenant, sections concatenated newest first."""
    t = check_tenant(tenant)
    keys = ("incidents", "pages", "acks", "actions", "contract_uses", "handoffs")
    secs: dict[str, list] = {k: [] for k in keys}
    seen: dict[str, set] = {k: set() for k in keys}
    queries, ms = [], 0.0
    for graph, ro in _each(t, graphs):
        try:
            r = ro.run("Q-SHIFT-REPORT", {"from": int(since), "to": int(until)})
        except GraphNotReady:
            continue
        row = r.rows[0] if r.rows else {}
        for k in keys:
            for item in row.get(k) or []:
                key = f"{item.get('id')}|{item.get('incident')}"
                if key not in seen[k]:
                    seen[k].add(key)
                    secs[k].append({**item, "graph": graph})
        ms += r.ms
        queries.append({"graph": graph, "ms": round(r.ms, 2), "digest": r.digest})

    def at(x: dict) -> int:
        return int(x.get("at") or x.get("sent_at") or x.get("opened_at") or 0)
    for k in keys:
        secs[k].sort(key=lambda x: (-at(x), str(x.get("id"))))
    counts = {k: len(v) for k, v in secs.items()}
    applied = sum(1 for a in secs["actions"] if a.get("verdict") == "APPLIED")
    people = sorted({p.get("person") for p in secs["pages"] if p.get("kind") in ("page", "escalation") and p.get("person")})
    summary = (f"{counts['incidents']} incident(s) opened; {sum(1 for p in secs['pages'] if p.get('kind') in ('page', 'escalation'))} "
               f"page(s) to {len(people)} person(s), {counts['acks']} acknowledged; {counts['actions']} approved action(s), "
               f"{applied} verified APPLIED; {counts['contract_uses']} handled under a standing contract; "
               f"{counts['handoffs']} hand-off(s).")
    return {**secs, "counts": counts, "window": {"from": int(since), "to": int(until)}, "summary": summary,
            "template": "Q-SHIFT-REPORT", "params": {"from": int(since), "to": int(until)}, "ms": round(ms, 2),
            "graphs": queries}


def stats(tenant: str, *, since: int, graphs: Iterable[str] | None = None) -> dict:
    """MTTA, MTTR, people paged and incidents handled under contract: Q-ONCALL-STATS in every graph of the tenant
    (per-incident durations computed in Cypher), the per-graph sums added here."""
    t = check_tenant(tenant)
    pages = acked = resolved = under = incidents = 0
    ack_sum = res_sum = 0.0
    people: set[str] = set()
    ack_all: list[float] = []
    res_all: list[float] = []
    queries, ms = [], 0.0
    for graph, ro in _each(t, graphs):
        try:
            r = ro.run("Q-ONCALL-STATS", {"since": int(since)})
        except GraphNotReady:
            continue
        row = r.rows[0] if r.rows else {}
        pages += int(row.get("pages") or 0)
        incidents += int(row.get("incidents_paged") or 0)
        people |= set(row.get("people") or [])
        acked += int(row.get("acked_incidents") or 0)
        ack_sum += float(row.get("ack_ms_sum") or 0.0)
        ack_all += [float(x) for x in row.get("ack_ms") or []]
        resolved += int(row.get("resolved_incidents") or 0)
        res_sum += float(row.get("resolve_ms_sum") or 0.0)
        res_all += [float(x) for x in row.get("resolve_ms") or []]
        under += int(row.get("under_contract") or 0)
        ms += r.ms
        queries.append({"graph": graph, "ms": round(r.ms, 2), "digest": r.digest})
    return {"since": int(since), "pages": pages, "incidents": incidents, "people_paged": len(people),
            "people": sorted(people), "acked_incidents": acked,
            "mtta_ms": round(ack_sum / acked) if acked else None, "resolved_incidents": resolved,
            "mttr_ms": round(res_sum / resolved) if resolved else None, "handled_under_contract": under,
            "template": "Q-ONCALL-STATS", "params": {"since": int(since)}, "ms": round(ms, 2), "graphs": queries}


__all__ = ["urgency_of", "ack_window_ms", "page_id", "page_token", "token_ok", "deep_link", "home_graph", "tenant_graphs",
           "recipients", "write_pages", "deliver", "deliver_wave", "wave_id", "tick", "escalate_now", "touch",
           "locate_incident", "locate_page", "ack",
           "on_approval", "page_after_approval",
           "settle_resolved", "approver_check", "oncall_now",
           "list_pages", "report", "stats", "page_view"]

_ = Any
