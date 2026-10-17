"""Learning from recent work and from the people who use it (M21, Track 2: agent memory & coordination).

Six loops, every one stored and decided in FalkorDB; this module only sequences hooks, reads and the arithmetic that
weights.yaml defines:

1. operator choices → (:Preference) per incident family and action kind (approvals minus rejections, recency-decayed,
   Beta-smoothed), read by PLAN through the `learned_preferences` tool; it REORDERS options within one predicted-future
   class (with verified outcomes, Q-REM-1) and says why;
2. rejections with a reason → (:Guideline {status: proposed}); a human promotes it (the option is then flagged and
   approving it needs an explicit override) or dismisses it; never a silent block;
3. acks, approvals and verified fixes → (:Person)-[:RESPONDED]->(component), read at ROUTE (`learned_responders`):
   the learned responder is paged in the first wave, before the rota (who is still paged);
4. the same exact fix approved and verified K times → the plan suggests a standing approval (the M19 two-step grant);
5. recall ranks precedents by similarity AND recency (Q-MEM-1) and says "last seen … ago, fixed by …";
6. brain questions the graph could not answer → (:KnowledgeGap), listed with the teams that should document them.

Trust (public demo): nothing an anonymous visitor does is learned. An action is learned only when the incident is
trusted (Incident.page_external: off the public demo, a keyed run or a keyed alert, M19's rule), the caller presented
the approver key, or it came through the operator-mapped Telegram bot. Learning never weakens the gate, an approval
or a contract: it reorders, suggests and annotates, and a promoted guideline only makes an approval stricter.

Every learned node derives from (:LearnEvent)s (DERIVED_FROM edges, or an `events` list on RESPONDED), and a person's
influence can be forgotten with a receipt (`forget_dry_run` → `forget_execute`). Everything lives in the tenant's
durable on-call home graph (oncall_<t>), never in a scenario's clean room.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from ..agent.weights import weights
from ..graph import client as gclient
from ..graph import writes
from ..graph.errors import GraphNotReady
from ..graph.ro import RO, canonical_json
from ..graph.tenant import audit_graph, check_tenant

log = logging.getLogger("faultline.learn")

CONTRACT_KINDS = ("flip_flag", "rollback_deploy")
KIND_WORD = {"flip_flag": "the flag flip", "rollback_deploy": "the rollback", "data_repair": "the data repair",
             "open_issue": "an issue"}
_ensured: set[str] = set()


def now_ms() -> int:
    return int(time.time() * 1000)


def w() -> dict:
    return weights()["learn"]


def half_life_ms() -> float:
    return float(w()["half_life_days"]) * 86_400_000


def home(tenant: str, ensure: bool = False) -> str:
    """The graph that holds what Faultline learned for a tenant: its durable on-call home graph (oncall_<t>, made once
    from golden_<t>; re-arm and seeding never replace it). Reads never write: the learning indexes on a home graph made
    before M21 are applied at API startup (`ensure_homes`) or, once per process, by a WRITE path (`ensure=True`)."""
    from ..actions import oncall

    name = oncall.home_graph(check_tenant(tenant))
    if ensure and name not in _ensured:
        writes.apply_schema(gclient.engine().select_graph(name))
        _ensured.add(name)
    return name


def ensure_homes(tenants: list[str]) -> dict[str, str]:
    """API startup: each tenant's on-call home graph exists and carries the schema (the M21 learning indexes on a home
    graph made before M21), so GET /api/learned and every other read stay read-only. Idempotent; never raises."""
    out = {}
    for t in tenants:
        try:
            out[t] = home(t, ensure=True)
        except Exception as e:  # noqa: BLE001 - an engine that is not ready yet: the first learning write retries it
            log.warning("learning: the on-call home graph of %s was not prepared at startup: %s", t, type(e).__name__)
    return out


def ago(ms: float | int | None) -> str:
    """A duration in words (the why lines): "just now", "4 min ago", "3 h ago", "2 days ago"."""
    if ms is None:
        return "never"
    s = max(0.0, float(ms) / 1000)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86_400:
        return f"{int(s // 3600)} h ago"
    d = int(s // 86_400)
    return f"{d} day{'s' if d != 1 else ''} ago"


def event_id(kind: str, *parts: Any) -> str:
    """Deterministic: the same action recorded twice (a retried hook) is one event."""
    return "le-" + hashlib.sha256("|".join([kind, *[str(p) for p in parts]]).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ trust and family
def trusted(tenant: str, graph: str, inc: str | None, *, key: bool = False, via: str | None = None) -> tuple[bool, str]:
    """May this action be learned? (M19's trust rule, applied to learning.) The approver key, the operator-mapped
    Telegram bot, an incident of the on-call graph (a keyed alert), or a trusted run (Incident.page_external, set at
    run start: off the public demo, or a run started with the approver key). Anything else is an anonymous visitor."""
    if key:
        return True, "approver key"
    if via == "telegram":
        return True, "Telegram (a person the operator mapped)"
    if graph == home(tenant, ensure=False):
        return True, "on-call graph (a keyed alert)"
    if inc:
        try:
            rows = RO(tenant, graph).run("Q-LEARN-TRUST", {"inc": inc}).rows
        except GraphNotReady:
            rows = []
        if rows and rows[0]["trusted"]:
            return True, "trusted run (off the public demo, or keyed)"
    return False, "an anonymous public-demo run: nothing it does is learned"


def family_of(ro: RO, run: str | None, inc: str) -> tuple[str | None, bool]:
    """An incident's family for learning: the component its gate-CONFIRMED cause changed (the contracts' family),
    else the component ROUTE ran who_fixes on (an inferred, unconfirmed origin). (family, confirmed)."""
    from ..actions import contracts

    fam = contracts.family_of(ro, inc)
    if fam:
        return fam, True
    if run:
        ev = ro.run("Q-EV-TOOL", {"run": run, "tool": "who_fixes"}).rows
        if ev and ev[0].get("params"):
            prm = json.loads(ev[0]["params"]) or {}
            t = prm.get("target") or (prm.get("Q-ORG-WHO") or {}).get("target")
            if t:
                return str(t), False
    return None, False


def _params_hash(kind: str, preview: Any) -> str | None:
    from ..actions import contracts

    if kind not in CONTRACT_KINDS:
        return None
    args = json.loads(preview) if isinstance(preview, str) else (preview or {})
    try:
        return contracts.params_hash(kind, contracts.action_params(kind, args))
    except (KeyError, contracts.ContractRefused):
        return None


# ------------------------------------------------------------------ recording (hooks; best effort, never fail the action)
def record(tenant: str, *, eid: str, kind: str, person: str, family: str | None, at: int | None = None,
           recompute: bool = True, **props: Any) -> dict:
    """One trusted event in the home graph, then the derived state it feeds, recomputed in Cypher (one query each)."""
    t = check_tenant(tenant)
    g = gclient.engine().select_graph(home(t, ensure=True))
    at = now_ms() if at is None else int(at)
    ev = writes.learn_event(g, eid=eid, kind=kind, person=person, family=family, at=at, **props)
    out: dict[str, Any] = {"event": ev["id"], "kind": kind}
    if recompute:
        out.update(_recompute(g, kind=kind, person=person, family=family, now=now_ms(), props=props, eid=eid))
    return out


def _recompute(g, *, kind: str, person: str, family: str | None, now: int, props: dict, eid: str) -> dict:
    lw = w()
    out: dict[str, Any] = {}
    if family and kind in ("approve", "reject"):
        out["preferences"] = writes.learn_recompute_prefs(g, family=family, now=now, half_life_ms=half_life_ms())
    if family and kind in ("approve", "ack", "verified") and person:
        out["responded"] = writes.learn_recompute_responder(
            g, person=person, family=family, now=now, half_life_ms=half_life_ms(), w_ack=float(lw["w_ack"]),
            w_approve=float(lw["w_approve"]), w_fix=float(lw["w_fix"]))
    if kind == "reject" and family and props.get("reason"):
        out["guideline"] = writes.learn_guideline(g, event=eid, gid="gl-" + eid.removeprefix("le-"),
                                                  text=str(props["reason"]))
    if kind == "gap" and props.get("gap"):
        out["gap"] = writes.learn_recompute_gap(g, gid=str(props["gap"]), text=str(props.get("text") or ""),
                                                intent=str(props.get("intent") or ""),
                                                reason=str(props.get("reason") or ""),
                                                about=list(props.get("about") or []), now=now)
    return out


def _safe(what: str, fn, *a, **kw) -> dict | None:
    """A hook never fails the operator's action: a learning failure is logged loudly and the action stands."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        log.error("learning: %s not recorded: %s: %s", what, type(e).__name__, e)
        return None


def _action_row(c, aid: str) -> dict | None:
    return next((a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid), None)


def _choice(c, aid: str, kind: str, person: str, *, key: bool, via: str | None, **extra: Any) -> dict | None:
    ok, why = trusted(c.tenant, c.graph, c.inc, key=key, via=via)
    if not ok:
        return {"learned": False, "why": why}
    a = _action_row(c, aid)
    if a is None:
        return {"learned": False, "why": f"{aid} is not part of {c.inc}'s plan"}
    fam, confirmed = family_of(c.ro(), c.run, c.inc)
    if not fam:
        return {"learned": False, "why": "no family: the incident has no confirmed cause and no routed component"}
    eid = event_id(kind, c.graph, c.inc, aid, *(extra.pop("_key", []) or []))
    rec = record(c.tenant, eid=eid, kind=kind, person=person, family=fam, incident=c.inc, graph=c.graph, run=c.run,
                 action=aid, action_kind=a["kind"], option=a["option"], target=a["target"],
                 params_hash=_params_hash(a["kind"], a.get("spec") and (json.loads(a["spec"]).get("args")) or a["preview"]),
                 confirmed=confirmed, trust=why, via=via or "web", **extra)
    return {"learned": True, "family": fam, **rec}


def on_choose(c, aid: str, person: str | None = None, *, key: bool = False, via: str | None = None) -> dict | None:
    """Choosing is recorded for provenance (who looked at what); it does not move a preference (approving does)."""
    return _safe("choose", _choice, c, aid, "choose", person or "", key=key, via=via, _key=[now_ms()])


def on_approve(c, aid: str, approver: str, *, key: bool = False, via: str | None = None,
               override: dict | None = None) -> dict | None:
    if str(approver).startswith("contract:"):   # a standing contract acted: not a person's choice
        return None
    out = _safe("approve", _choice, c, aid, "approve", approver, key=key, via=via)
    if override and out and out.get("learned"):
        _safe("override", _choice, c, aid, "override", approver, key=key, via=via, guideline=override.get("id"),
              reason=override.get("reason"), _key=[override.get("id")])
    return out


def on_reject(c, aid: str, approver: str, reason: str, *, key: bool = False) -> dict | None:
    """A trusted rejection with a reason: a negative choice for the preference, and a PROPOSED guideline."""
    return _safe("reject", _choice, c, aid, "reject", approver, key=key, via=None, reason=" ".join(reason.split())[:500])


def on_ack(tenant: str, graph: str, res: dict, *, via: str, key: bool = False) -> dict | None:
    """A PERSON acknowledged a page (not the anonymous run-token holder; not an approval, which is its own event):
    a response to the incident's family, with the delay from that page to the ack."""
    def go() -> dict:
        if not res or not res.get("by") or via == "approval":
            return {"learned": False, "why": "not a person's acknowledgement"}
        inc = res.get("incident")
        ok, why = trusted(tenant, graph, inc, key=key, via=via)
        if not ok:
            return {"learned": False, "why": why}
        ro = RO(tenant, graph)
        page = (ro.run("Q-PAGE-ONE", {"page": res["page"], "now": now_ms()}).rows or [{}])[0]
        loc = None
        if inc:
            from ..actions import oncall

            loc = oncall.locate_incident(tenant, inc)
        fam, confirmed = family_of(ro, (loc or {}).get("run"), inc) if inc else (None, False)
        if not fam:
            return {"learned": False, "why": "no family for the page's incident"}
        at = int(res.get("at") or now_ms())
        sent = page.get("sent_at")
        return {"learned": True, "family": fam, **record(
            tenant, eid=event_id("ack", graph, res["page"]), kind="ack", person=res["by"], family=fam, at=at,
            incident=inc, graph=graph, page=res["page"], ack_ms=(at - int(sent)) if sent is not None else None,
            via=via, trust=why, confirmed=confirmed)}
    return _safe("ack", go)


def on_verified(c, aid: str) -> dict | None:
    """After the execute job: an approved fix verified APPLIED and RESOLVED is learned when its approval was (the
    approve event exists, so the approver was trusted): a response by the approver, and a count towards the contract
    suggestion for exactly this fix."""
    def go() -> dict:
        a = _action_row(c, aid)
        stage = (c.ro().run("Q-INC-1", {"inc": c.inc}).rows or [{}])[0].get("stage")
        if not a or a.get("verdict") != "APPLIED" or stage != "RESOLVED":
            return {"learned": False, "why": "not verified APPLIED and resolved"}
        g = home(c.tenant)
        appr = RO(c.tenant, g).run("Q-LEARN-EV1", {"id": event_id("approve", c.graph, c.inc, aid)}).rows
        if not appr:
            return {"learned": False, "why": "its approval was not learned (untrusted, or a standing contract acted)"}
        ap = appr[0]
        spec = json.loads(a["spec"]) if a.get("spec") else {}
        return {"learned": True, "family": ap["family"], **record(
            c.tenant, eid=event_id("verified", c.graph, c.inc, aid), kind="verified", person=ap["person"],
            family=ap["family"], incident=c.inc, graph=c.graph, run=c.run, action=aid, action_kind=a["kind"],
            option=a["option"], target=a["target"], verdict="APPLIED",
            params_hash=_params_hash(a["kind"], spec.get("args") or a.get("preview")), via=ap.get("via"))}
    return _safe("verified", go)


def on_note(tenant: str, kind: str, person: str, *, key_parts: list, family: str | None = None, trusted_: bool = True,
            **props: Any) -> dict | None:
    """Provenance-only events (grant, revoke, hand-off, escalate now): recorded for who did what; they feed no
    derived state."""
    if not trusted_ or not person:
        return None
    return _safe(kind, record, tenant, eid=event_id(kind, *key_parts), kind=kind, person=person, family=family,
                 recompute=False, **props)


# ------------------------------------------------------------------ knowledge gaps (brain)
_GAP_TEXT = re.compile(r"^(I can't answer that from the graph|No decision about that is documented|I could not find "
                       r"that component|Nothing is recorded in|Nobody has committed to|No team owned|Answer withheld)")


def gap_reason(intent: str, answer: str) -> str | None:
    """Why a brain answer is a knowledge gap, or None when it answered. Refused (no kind of question matched), nothing
    documented, or withheld by the citation guard; the router's and the guard's own words, never a guess."""
    a = (answer or "").strip()
    if intent == "none" and a.startswith("I can't answer that from the graph"):
        if "not a question about the organisation" in a:   # small talk or a request to act: nothing to document
            return None
        return "refused: " + a.split(":", 1)[-1].strip()[:200]
    if _GAP_TEXT.match(a):
        return "unanswered: " + a[:200]
    return None


def normalise(q: str) -> str:
    return " ".join(re.findall(r"[a-z0-9][a-z0-9_.-]*", (q or "").lower()))[:300]


def on_gap(tenant: str, answer: dict, user: str | None, *, trusted_: bool) -> dict | None:
    """A trusted question the graph could not answer becomes (or counts towards) a KnowledgeGap. `answer` is
    brain.ask's Answer.as_dict(); its resolve_entity steps say what the question was about."""
    if not trusted_:
        return None
    reason = gap_reason(str(answer.get("intent") or ""), str(answer.get("answer") or ""))
    if reason is None:
        return None
    text = normalise(answer.get("question") or "")
    if not text:
        return None
    gid = "kg-" + hashlib.sha256(text.encode()).hexdigest()[:14]
    about = sorted({str((s.get("args") or {}).get("text")) for s in answer.get("steps") or []
                    if s.get("tool") == "resolve_entity" and s.get("rows") and (s.get("args") or {}).get("text")})
    return _safe("gap", record, tenant, eid=event_id("gap", answer.get("run_id") or now_ms()), kind="gap",
                 person=user or "operator", family=None, gap=gid, text=str(answer.get("question") or "")[:500],
                 intent=str(answer.get("intent") or ""), reason=reason, about=about, run=answer.get("run_id"))


# ------------------------------------------------------------------ PLAN: reorder (within a future class), annotate
def _pref_line(kind: str, p: dict, family: str, now: int) -> str:
    na, tna, nr = int(p.get("n_approve") or 0), int(p.get("n_family_approve") or 0), int(p.get("n_reject") or 0)
    bits = [f"learned: your team approved {KIND_WORD.get(kind, kind)} {na} of the last {tna} time(s) for {family}"]
    if nr:
        bits.append(f"rejected it {nr} time(s)")
    if p.get("last_at"):
        bits.append(f"last {ago(now - int(p['last_at']))}")
    return "; ".join(bits)


def plan_view(learned: dict | None) -> dict:
    """The learned_preferences tool result as the ordering needs it: preference rows by kind, the family's total
    decayed approvals, whether there are enough choices to reorder (learn.pref_min_n), the guidelines by kind and
    the contract suggestions by (kind, params hash)."""
    if not learned or "error" in learned:
        return {"applies": False, "prefs": {}, "guides": {}, "suggest": {}, "n_family": 0, "family": None,
                "error": (learned or {}).get("error")}
    rows = learned.get("rows") or []
    prefs = {r["action_kind"]: r for r in rows}
    n_family = max([int(r.get("n_family") or 0) for r in rows] or [0])
    guides: dict[str, list] = {}
    for gd in learned.get("guidelines") or []:
        guides.setdefault(gd["action_kind"], []).append(gd)
    suggest = {(s["action_kind"], s["params_hash"]): s for s in learned.get("suggestions") or [] if not s.get("covered")}
    return {"applies": n_family >= int(w()["pref_min_n"]), "prefs": prefs, "guides": guides, "suggest": suggest,
            "n_family": n_family, "family": learned.get("family"), "now": int(learned.get("now") or now_ms()),
            "total_approvals": sum(float(r.get("approvals") or 0.0) for r in rows),
            "evidence_id": learned.get("evidence_id")}


def pref_of(view: dict, kind: str) -> float | None:
    """The Beta-smoothed preference for one action kind on this family; a kind never approved scores
    1 / (total approvals + 2). None when the family has too few choices to say anything."""
    if not view.get("applies"):
        return None
    p = view["prefs"].get(kind)
    if p is not None:
        return float(p["pref"])
    return 1.0 / (float(view.get("total_approvals") or 0.0) + 2.0)


def annotate(o: dict, view: dict) -> dict:
    """The learned annotations of one option (never changes enabled, never adds or removes one): the preference line,
    the guidelines on its family and kind (an ACTIVE one needs an explicit override to approve it) and, for a contract
    kind, the standing-approval suggestion."""
    if not view.get("family"):
        return {}
    out: dict[str, Any] = {"family": view["family"]}
    now = int(view.get("now") or now_ms())
    p = view["prefs"].get(o["kind"])
    if view.get("applies") and o.get("enabled") and o["kind"] != "open_issue":
        pref = pref_of(view, o["kind"])
        out["preference"] = {"pref": round(float(pref), 4), "n_approve": int((p or {}).get("n_approve") or 0),
                             "n_reject": int((p or {}).get("n_reject") or 0),
                             "n_family_approve": int((p or {}).get("n_family_approve") or
                                                     max([int(x.get("n_family_approve") or 0) for x in view["prefs"].values()] or [0])),
                             "last_at": (p or {}).get("last_at"), "events": ((p or {}).get("events") or [])[:20],
                             "line": _pref_line(o["kind"], p or {"n_family_approve": max(
                                 [int(x.get("n_family_approve") or 0) for x in view["prefs"].values()] or [0])},
                                 view["family"], now)}
    gds = (view["guides"].get(o["kind"]) or []) if o.get("enabled") else []   # a disabled option cannot be approved
    active = [g for g in gds if g["status"] == "active"]
    shown = active[0] if active else (gds[0] if gds else None)
    if shown:
        who = shown.get("by_name") or shown.get("by")
        out["guideline"] = {"id": shown["id"], "text": shown["text"], "status": shown["status"], "by": shown.get("by"),
                            "by_name": shown.get("by_name"), "at": shown.get("at"), "incident": shown.get("incident"),
                            "event": shown.get("event"), "needs_override": bool(active),
                            "decided_by": shown.get("decided_by"), "decided_by_name": shown.get("decided_by_name"),
                            "decided_at": shown.get("decided_at"),
                            "line": (f"against your guideline {shown['id']}: \"{shown['text']}\" ({who}, promoted by "
                                     f"{shown.get('decided_by_name') or shown.get('decided_by')}); approving it needs an "
                                     "explicit override") if active else
                                    (f"proposed guideline {shown['id']} from {who}'s rejection {ago(now - int(shown['at'] or now))}: "
                                     f"\"{shown['text']}\" (not active: promote or dismiss it)")}
        if len(gds) > 1:
            out["guideline"]["others"] = [g["id"] for g in gds if g["id"] != shown["id"]][:5]
    if o["kind"] in CONTRACT_KINDS and o.get("args"):
        ph = _params_hash(o["kind"], o["args"])
        s = view["suggest"].get((o["kind"], ph)) if ph else None
        if s:
            out["contract_suggestion"] = {"n": int(s["n"]), "params_hash": ph, "incidents": s.get("incidents") or [],
                                          "events": s.get("events") or [], "people": s.get("people") or [],
                                          "line": (f"this exact fix was approved and verified APPLIED on {int(s['n'])} "
                                                   f"incidents of {view['family']}: once it is verified here, grant a "
                                                   "standing approval for repeats? (still two steps)")}
    return out


def plan_summary(options: list[dict], learned: dict | None) -> dict:
    """What learning did to this plan (for the plan, the report and the UI): applied, moved, the family, guidelines
    needing an override, contract suggestions, and the evidence id of the learned_preferences read."""
    if learned is None:
        return {"applied": False, "moved": False, "note": "learning not consulted (no on-call home: benches, CLI, evals)"}
    if "error" in learned:
        return {"applied": False, "moved": False, "note": f"learned preferences unavailable ({learned['error']}); "
                                                          "order without learning kept"}
    view = plan_view(learned)
    moved = [o["id"] for i, o in enumerate(options, 1)
             if (o.get("learned") or {}).get("rank_without_learning") not in (None, i)]
    flagged = [o["id"] for o in options if ((o.get("learned") or {}).get("guideline") or {}).get("needs_override")]
    suggest = [o["id"] for o in options if (o.get("learned") or {}).get("contract_suggestion")]
    note = (f"{view['n_family']} recorded choice(s) for {view['family']}"
            + ("" if view["applies"] else f" (fewer than learn.pref_min_n = {int(w()['pref_min_n'])}: order unchanged)")
            + (f"; reordered: {', '.join(moved)}" if moved else "")
            + (f"; {len(flagged)} option(s) against an active guideline" if flagged else "")
            + (f"; contract suggested for {', '.join(suggest)}" if suggest else ""))
    return {"applied": bool(view["applies"]), "moved": bool(moved), "family": view["family"], "n_family": view["n_family"],
            "flagged": flagged, "suggested": suggest, "evidence_id": learned.get("evidence_id"), "note": note}


# ------------------------------------------------------------------ ROUTE: learned responders
def first_wave(resp: dict | None) -> list[dict]:
    """Who learning adds to the first wave of pages (learn.resp_first_wave at most): active people whose RESPONDED edge
    to the family rests on ≥ learn.resp_min_n events, best decayed score first (Q-LEARN-RESP's order). Additive only."""
    if not resp or "error" in resp:
        return []
    lw = w()
    out = []
    for r in resp.get("rows") or []:
        if int(r.get("n") or 0) < int(lw["resp_min_n"]):
            continue
        bits = [f"{int(r.get('acks') or 0)} ack(s)", f"{int(r.get('approvals') or 0)} approval(s)",
                f"{int(r.get('fixes') or 0)} verified fix(es)"]
        mtta = r.get("mtta_ms")
        reason = (f"learned responder for {resp.get('target')}: answered {int(r.get('incidents') or 0)} incident(s) "
                  f"({', '.join(bits)}" + (f", mean ack {round(float(mtta) / 1000)} s" if mtta is not None else "")
                  + ")" + (f", last {ago(int(resp.get('now') or now_ms()) - int(r['last_at']))}" if r.get("last_at")
                           else "") + " (Q-LEARN-RESP); the rota on-call is paged too")
        out.append({"person": r["person"], "team": "", "reason": reason, "evidence": resp.get("evidence_id") or "",
                    "learned": True, "score": round(float(r["score"]), 4)})
        if len(out) >= int(lw["resp_first_wave"]):
            break
    return out


def blend_who(who_rows: list[dict], resp: dict | None) -> list[dict]:
    """who_fixes blended with learned responders (learn.w_resp): (1 - w) × harmonic score / top score + w × s / (s +
    resp_sat). Display and paging order only; Q-ORG-HARM's own ranking is unchanged and recorded."""
    lw = w()
    wr, sat = float(lw["w_resp"]), float(lw["resp_sat"])
    by = {r["person"]: r for r in (resp or {}).get("rows") or []} if resp and "error" not in resp else {}
    top = max([float(x.get("score") or 0.0) for x in who_rows] or [0.0]) or 1.0
    out = []
    for x in who_rows:
        s = float((by.get(x["person"]) or {}).get("score") or 0.0)
        out.append({**x, "harmonic": x.get("score"), "responded": round(s, 4),
                    "blended": round((1 - wr) * float(x.get("score") or 0.0) / top + wr * s / (s + sat), 4)})
    for pid, r in by.items():   # a responder the projection does not reach is still shown (with no harmonic score)
        if pid not in {x["person"] for x in who_rows}:
            s = float(r.get("score") or 0.0)
            out.append({"person": pid, "name": r.get("name"), "score": None, "harmonic": None, "teams": [],
                        "reasons": ["learned responder (not in the who_fixes projection)"], "oncall": False,
                        "responded": round(s, 4), "blended": round(wr * s / (s + sat), 4)})
    return sorted(out, key=lambda x: (-x["blended"], x["person"]))


# ------------------------------------------------------------------ the learned state (API, MCP)
def _qr(r) -> dict:
    return {"rows": r.rows, "template": r.template_id, "params": r.params, "ms": round(r.ms, 2), "truncated": r.truncated,
            "digest": r.digest}


def state(tenant: str, now: int | None = None) -> dict:
    """Everything learned for a tenant, each section with the FalkorDB query that produced it (UI-ready)."""
    t = check_tenant(tenant)
    now = now_ms() if now is None else int(now)
    g = home(t)
    ro = RO(t, g)
    hl = half_life_ms()
    prefs = ro.run("Q-LEARN-PREFS", {"now": now, "half_life_ms": hl})
    guides = ro.run("Q-LEARN-GUIDES", {"statuses": ["proposed", "active", "dismissed"]})
    resp = ro.run("Q-LEARN-RESPS", {"now": now, "half_life_ms": hl})
    gaps = ro.run("Q-KGAP-1", {"statuses": ["open", "dismissed"]})
    sugg = ro.run("Q-LEARN-SUGGESTS", {"k": int(w()["contract_suggest_k"])})
    events = ro.run("Q-LEARN-EVENTS", {})
    counts = ro.run("Q-LEARN-COUNTS", {})
    try:
        receipts = _qr(RO(t, audit_graph(t)).run("Q-LEARN-RECEIPTS", {}))
    except GraphNotReady:   # no audit graph yet: nothing was ever forgotten
        receipts = {"rows": [], "template": "Q-LEARN-RECEIPTS", "params": {}, "ms": 0.0, "truncated": False, "digest": ""}
    pv = _qr(prefs)
    for r in pv["rows"]:
        r["line"] = _pref_line(r["action_kind"], r, r["family"], now)
    sv = _qr(sugg)
    for s in sv["rows"]:
        m = ro.run("Q-CONTRACT-MATCH", {"family": s["family"], "kind": s["action_kind"], "params_hash": s["params_hash"],
                                        "now": now}).rows
        s["covered_by"] = m[0]["id"] if m else None
    rv = _qr(resp)
    for r in rv["rows"]:
        r["person"] = {"id": r["person"], "name": r.pop("name")}
    gv = _qr(guides)
    for x in gv["rows"]:
        x["by"] = {"id": x["by"], "name": x.pop("by_name")}
        x["decided_by"] = {"id": x["decided_by"], "name": x.pop("decided_by_name")} if x.get("decided_by") else None
    return {"tenant": t, "home": g, "now": now, "half_life_days": float(w()["half_life_days"]),
            "trust": {"rule": "learned only from trusted actors: a run off the public demo or started with the approver "
                              "key, a keyed alert, the approver key, or the operator-mapped Telegram bot",
                      "public": _public()},
            "preferences": pv, "guidelines": gv, "responders": rv, "gaps": _qr(gaps), "suggestions": sv,
            "events": {**_qr(events), "counts": counts.rows}, "receipts": receipts}


def _public() -> bool:
    from ..config import settings

    return bool(settings.faultline_public)


def guideline(tenant: str, gid: str) -> dict | None:
    rows = RO(check_tenant(tenant), home(tenant)).run("Q-LEARN-GUIDE-1", {"id": gid}).rows
    return rows[0] if rows else None


def set_guideline(tenant: str, gid: str, action: str, by: str, now: int | None = None) -> dict | None:
    """Promote (proposed → active) or dismiss (proposed | active → dismissed), by an active person. None ⇒ unknown
    guideline, not in a status that allows it, or `by` is not an active person (HTTP 409)."""
    g = gclient.engine().select_graph(home(tenant, ensure=True))
    res = writes.learn_set_guideline(g, gid=gid, action=action, by=by, now=now_ms() if now is None else int(now))
    if res is None:
        return None
    return guideline(tenant, gid)   # who decided and when are on the guideline itself (decided_by, decided_at)


def dismiss_gap(tenant: str, gid: str, by: str, now: int | None = None) -> dict | None:
    return writes.learn_dismiss_gap(gclient.engine().select_graph(home(tenant, ensure=True)), gid=gid, by=by,
                                    now=now_ms() if now is None else int(now))


def active_guidelines(tenant: str, family: str, kind: str) -> list[dict]:
    """ACTIVE guidelines against an action kind on a family, read fresh at approval time (Q-LEARN-GUIDE)."""
    try:
        rows = RO(check_tenant(tenant), home(tenant, ensure=False)).run(
            "Q-LEARN-GUIDE", {"family": family, "statuses": ["active"]}).rows
    except GraphNotReady:
        return []
    return [r for r in rows if r["action_kind"] == kind]


# ------------------------------------------------------------------ forget a person's influence, with a receipt
class ForgetRefused(PermissionError):
    """The forget cannot be done as approved (too many events to list, or the set changed): nothing deleted."""


def _person_events(tenant: str, person: str) -> list[dict]:
    ro = RO(check_tenant(tenant), home(tenant))
    out: list[dict] = []
    after_at, after_id = -1, ""
    for _ in range(int(w()["forget_pages"])):
        page = ro.run("Q-LEARN-PERSON", {"person": person, "after_at": after_at, "after_id": after_id})
        out += page.rows
        if not page.truncated:
            return out
        after_at, after_id = int(page.rows[-1]["at"]), page.rows[-1]["id"]
    raise ForgetRefused(f"{person} has more learning events than the dry run can list "
                        f"({int(w()['forget_pages'])} pages): refused rather than approving a partial list")


def _token(tenant: str, person: str, events: list[dict]) -> str:
    return hashlib.sha256(canonical_json({"tenant": tenant, "person": person, "kind": "learned_influence",
                                          "events": sorted(e["id"] for e in events)}).encode()).hexdigest()


def forget_dry_run(tenant: str, person: str) -> dict:
    """What forgetting a person's learned influence deletes and recomputes, and the receipt token that binds the
    approval to exactly this set (the same idea as the plan hash)."""
    t = check_tenant(tenant)
    evs = _person_events(t, person)
    fams = sorted({e["family"] for e in evs if e.get("family")})
    return {"person": person, "events": evs, "n_events": len(evs),
            "by_kind": {k: sum(1 for e in evs if e["kind"] == k) for k in sorted({e["kind"] for e in evs})},
            "guidelines": sorted({g for e in evs for g in e.get("guidelines") or []}),
            "families": fams, "responded": [f for f in fams if any(e["family"] == f and e["kind"] in
                                                                    ("ack", "approve", "verified") for e in evs)],
            "gaps": sorted({e["gap"] for e in evs if e.get("gap")}), "token": _token(t, person, evs)}


def forget_execute(tenant: str, person: str, token: str, approver: str) -> dict:
    """Delete exactly the dry run's events (and the guidelines they proposed) in one query, recompute every derived
    item they fed (one query each), write a ForgetReceipt to audit_<t>, and prove it: re-read the person's events
    (none left) and every affected preference / responder edge."""
    t = check_tenant(tenant)
    plan = forget_dry_run(t, person)
    if plan["token"] != token:
        raise PermissionError("the dry-run receipt no longer matches the learned state; run the dry run again")
    g = gclient.engine().select_graph(home(t, ensure=True))
    done = writes.learn_forget(g, person=person, ids=[e["id"] for e in plan["events"]])
    now = now_ms()
    lw = w()
    for f in plan["families"]:
        writes.learn_recompute_prefs(g, family=f, now=now, half_life_ms=half_life_ms())
    for f in plan["responded"]:
        writes.learn_recompute_responder(g, person=person, family=f, now=now, half_life_ms=half_life_ms(),
                                         w_ack=float(lw["w_ack"]), w_approve=float(lw["w_approve"]),
                                         w_fix=float(lw["w_fix"]))
    gap_rows = {e["gap"]: e for e in plan["events"] if e.get("gap")}
    for gid, e in gap_rows.items():
        writes.learn_recompute_gap(g, gid=gid, text=str(e.get("text") or ""), intent=str(e.get("intent") or ""),
                                   reason=str(e.get("reason") or ""), about=list(e.get("about") or []), now=now)
    left = _person_events(t, person)
    ro = RO(t, home(t))
    still = [r for f in plan["families"] for r in ro.run("Q-LEARN-PREF", {"family": f, "now": now,
                                                                          "half_life_ms": half_life_ms()}).rows
             if set(r.get("events") or []) & {e["id"] for e in plan["events"]}]
    receipt = {"tenant": t, "graph": home(t), "kind": "learned_influence", "person": person, "approver": approver,
               "token": token, "events": done["events"], "guidelines": done["guidelines"],
               "relationships": done["relationships"], "families_recomputed": json.dumps(plan["families"]),
               "responders_recomputed": json.dumps(plan["responded"]), "gaps_recomputed": json.dumps(sorted(gap_rows)),
               "events_left": len(left), "preferences_still_citing": len(still), "at": now}
    writes.append_audit(gclient.engine().select_graph(audit_graph(t)), "ForgetReceipt", receipt)
    return {**receipt, "families_recomputed": plan["families"], "responders_recomputed": plan["responded"],
            "gaps_recomputed": sorted(gap_rows),
            "proof": {"events_left": len(left), "preferences_still_citing": len(still),
                      "verdict": "forgotten" if not left and not still else "INCOMPLETE (events or citations remain)"}}


__all__ = ["home", "ensure_homes", "trusted", "family_of", "record", "on_choose", "on_approve", "on_reject", "on_ack", "on_verified",
           "on_note", "on_gap", "gap_reason", "plan_view", "pref_of", "annotate", "plan_summary", "first_wave",
           "blend_who", "state", "set_guideline", "dismiss_gap", "active_guidelines", "forget_dry_run",
           "forget_execute", "ForgetRefused", "ago", "now_ms", "half_life_ms", "event_id"]
