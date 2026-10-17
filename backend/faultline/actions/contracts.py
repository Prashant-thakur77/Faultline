"""Standing approvals ("contracts"; the Sleep Contracts of the author's Beacon project, adapted to FalkorDB).

A contract lets Faultline run ONE production-changing action again, without waking anyone, when the same fault comes
back: same family (the component the gate-confirmed cause changed), same action kind, same parameters (hash), a
limited number of times, until it expires. Everything else is unchanged:

* it is granted only after that action was verified APPLIED, by a person Q-APPROVER-1 says may approve on that
  incident, in two steps bound to a hash (choose the scope → an offer; approve that exact hash → active), single use,
  within weights.yaml oncall.contract_offer_ttl_s;
* it applies only after the gate CONFIRMS a cause (G1–G8 unchanged): an abstention, a NOT_CONFIDENT pass or an
  inferred origin never reaches it; the plan's family, action and params hash must match and Q-CONTRACT-MATCH must
  return a row;
* then ONE guarded write (W_CONTRACT_USE: active, uses < max_uses, expires_at > now, same family/action/params, the
  grantor still active) consumes a use, the action runs without paging, verification still runs, and NOT_APPLIED or
  UNKNOWN pages a human at once (api._contract_job);
* a human can revoke it at any time.

Contracts live in the tenant's on-call home graph (oncall.home_graph: the tenant graph), never in a scenario's clean
room, because they outlive the incident that granted them.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from ..agent.weights import weights
from ..graph import client as gclient
from ..graph import writes
from ..graph.ro import RO, canonical_json

CONTRACT_KINDS = ("flip_flag", "rollback_deploy")   # production changes verified through GitHub main + telemetry


class ContractRefused(ValueError):
    """The contract cannot be offered or granted (HTTP 409/422 with this text)."""


def now_ms() -> int:
    return int(time.time() * 1000)


def action_params(kind: str, args: dict) -> dict:
    """The part of an action's arguments a contract binds: WHAT changes in production (repository, file, flag and
    state, or service and the change reverted), never who is suggested as reviewer."""
    if kind == "flip_flag":
        return {"repo": args["repo"], "path": args["path"], "flag": args["flag"], "state": args["state"]}
    if kind == "rollback_deploy":
        return {"repo": args["repo"], "path": args["path"], "service": args["service"], "revert": args["revert"]}
    raise ContractRefused(f"a standing contract covers {', '.join(CONTRACT_KINDS)} only, not {kind}")


def params_hash(kind: str, params: dict) -> str:
    """Stable identity of (action, params), so a contract and a later plan can be compared (Beacon's params_hash)."""
    return hashlib.sha256(canonical_json({"action": kind, "params": params}).encode()).hexdigest()


def family_of(ro: RO, inc: str) -> str | None:
    """The incident's family for contracts: the component its gate-CONFIRMED cause changed (Q-CAUSE-1 → Q-CHANGE-1).
    None when the gate confirmed no cause (abstention, NOT_CONFIDENT, an inferred origin): no contract applies."""
    cause = (ro.run("Q-CAUSE-1", {"inc": inc}).rows or [{}])[0].get("cause")
    if not cause:
        return None
    return (ro.run("Q-CHANGE-1", {"id": cause}).rows or [{}])[0].get("target")


def _limits() -> tuple[int, float, int]:
    w = weights()["oncall"]
    return int(w["contract_max_uses"]), float(w["contract_max_days"]), int(w["contract_offer_ttl_s"]) * 1000


def offer(*, tenant: str, graph: str, inc: str, home: str, max_uses: int, days: float, now: int | None = None,
          action_id: str | None = None) -> dict:
    """Step 1: the exact grant (scope + hash), recorded as an OFFER in the home graph. Reads the incident's verified
    APPLIED action from its own graph; refuses when there is none, it is not a contract kind or the gate confirmed no
    cause."""
    now = now_ms() if now is None else int(now)
    cap_uses, cap_days, ttl_ms = _limits()
    if not 1 <= int(max_uses) <= cap_uses:
        raise ContractRefused(f"max_uses must be 1..{cap_uses} (weights.yaml oncall.contract_max_uses)")
    if not 0 < float(days) <= cap_days:
        raise ContractRefused(f"days must be > 0 and ≤ {cap_days:g} (weights.yaml oncall.contract_max_days)")
    ro = RO(tenant, graph)
    acts = [a for a in ro.run("Q-ACT-1", {"inc": inc}).rows if a["verdict"] == "APPLIED"
            and (action_id is None or a["id"] == action_id)]
    if not acts:
        raise ContractRefused(f"{inc} has no action verified APPLIED: a contract is granted only after a verified fix")
    act = acts[0]
    if act["kind"] not in CONTRACT_KINDS:
        raise ContractRefused(f"{act['option']} ({act['kind']}) is not a production change a contract may repeat "
                              f"(only {', '.join(CONTRACT_KINDS)})")
    family = family_of(ro, inc)
    if not family:
        raise ContractRefused(f"the gate confirmed no cause for {inc}: no family to bind a contract to")
    spec = json.loads(act["spec"] or "{}")
    params = action_params(act["kind"], spec.get("args") or {})
    ph = params_hash(act["kind"], params)
    expires_at = now + int(float(days) * 86_400_000)
    scope = {"family": family, "action_kind": act["kind"], "params_hash": ph, "params": params, "max_uses": int(max_uses),
             "days": float(days), "expires_at": expires_at}
    h = hashlib.sha256(canonical_json({**scope, "tenant": tenant, "incident": inc, "action": act["id"]}).encode()).hexdigest()
    cid = f"ct-{h[:16]}"
    until = datetime.fromtimestamp(expires_at / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    quote = (f"Standing approval: {act['option']} without paging, whenever the gate confirms a change on {family} as the "
             f"cause and the plan offers exactly this change; at most {int(max_uses)} time(s), until {until}. "
             f"Verification still runs; anything but APPLIED pages a human.")
    rec = writes.offer_contract(gclient.engine().select_graph(home), cid=cid, tenant=tenant, family=family,
                                kind=act["kind"], params_hash=ph, params=params, max_uses=int(max_uses), days=float(days),
                                expires_at=expires_at, now=now, ttl_ms=ttl_ms, hash_=h, inc=inc, graph=graph, aid=act["id"],
                                covers=family, quote=quote)
    if rec["status"] != "offered":
        raise ContractRefused(f"contract {cid} is already {rec['status']}")
    return {"hash": h, "contract_id": cid, "scope": scope, "quote": quote, "action": act["id"], "option": act["option"],
            "offer_expires_at": rec["offer_expires_at"], "home": home,
            "step": "approve: send this hash back with an approver (step 2); nothing is active until then"}


def grant(*, tenant: str, home: str, hash_: str, by: str, now: int | None = None, real_ok: bool = False) -> dict | None:
    """Step 2: approve exactly that offer. None ⇒ unknown, stale or expired offer, already granted (HTTP 409).
    `real_ok`: the grant was made with the authority real GitHub needs (the caller checked it); a contract without it
    never acts while GitHub is real."""
    now = now_ms() if now is None else int(now)
    cid = f"ct-{hash_[:16]}"
    rows = [r for r in RO(tenant, home).run("Q-CONTRACT-OFFER", {"id": cid}).rows]
    covers = rows[0]["covers"] if rows else ""
    res = writes.grant_contract(gclient.engine().select_graph(home), cid=cid, hash_=hash_, by=by, covers=covers or "",
                                now=now, real_ok=real_ok)
    if res is None:
        return None
    return one(tenant, home, cid, now)


def offer_row(tenant: str, home: str, hash_: str) -> dict | None:
    rows = RO(tenant, home).run("Q-CONTRACT-OFFER", {"id": f"ct-{hash_[:16]}"}).rows
    return rows[0] if rows else None


def one(tenant: str, home: str, cid: str, now: int | None = None) -> dict | None:
    rows = [r for r in listing(tenant, home, now)["rows"] if r["id"] == cid]
    return rows[0] if rows else None


def listing(tenant: str, home: str, now: int | None = None) -> dict:
    now = now_ms() if now is None else int(now)
    r = RO(tenant, home).run("Q-CONTRACTS", {"now": now})
    rows = []
    for x in r.rows:
        params = x.get("params")
        rows.append({**x, "params": json.loads(params) if isinstance(params, str) and params else params,
                     "granted_by": {"id": x["granted_by"], "name": x.get("granted_by_name")},
                     "used_in": sorted(x.get("used_in") or [], key=lambda u: -(u.get("at") or 0))})
    return {"rows": rows, "template": r.template_id, "params": r.params, "ms": round(r.ms, 2), "truncated": r.truncated,
            "digest": r.digest, "home": home}


def match_plan(*, tenant: str, home: str, family: str | None, options: list[dict], now: int | None = None) -> dict:
    """Does a standing contract cover this plan? Only for a gate-confirmed family; for each ENABLED option of a
    contract kind (plan order), its params hash against Q-CONTRACT-MATCH in the home graph. Returns {"match": …} or
    {"match": None, "why": …}, with every query it ran (evidence for the decision)."""
    now = now_ms() if now is None else int(now)
    if not family:
        return {"match": None, "why": "the gate confirmed no cause: a contract never applies", "queries": []}
    ro = RO(tenant, home)
    queries = []
    for o in options:
        if not o.get("enabled") or o.get("kind") not in CONTRACT_KINDS or not o.get("args"):
            continue
        try:
            ph = params_hash(o["kind"], action_params(o["kind"], o["args"]))
        except (KeyError, ContractRefused):
            continue
        r = ro.run("Q-CONTRACT-MATCH", {"family": family, "kind": o["kind"], "params_hash": ph, "now": now})
        queries.append({"template": r.template_id, "params": r.params, "rows": len(r.rows), "digest": r.digest,
                        "option": o["id"]})
        if r.rows:
            return {"match": {**r.rows[0], "option": o["id"], "option_text": o.get("option"), "kind": o["kind"],
                              "params_hash": ph, "family": family}, "queries": queries}
    why = (f"no active, unexpired, unexhausted contract covers family {family} with this plan's action and parameters"
           if queries else "no enabled option of a kind a contract may repeat")
    return {"match": None, "why": why, "queries": queries}


def use(*, home: str, match: dict, inc: str, graph: str, aid: str, now: int | None = None) -> dict | None:
    """THE guarded use (one write). None ⇒ exhausted, expired, revoked or changed since the match: page a human."""
    now = now_ms() if now is None else int(now)
    uid = "cu-" + hashlib.sha256(f"{match['id']}|{graph}|{inc}|{aid}".encode()).hexdigest()[:14]
    return writes.use_contract(gclient.engine().select_graph(home), cid=match["id"], family=match["family"],
                               kind=match["kind"], params_hash=match["params_hash"], uid=uid, inc=inc, graph=graph,
                               aid=aid, now=now)


def give_back(*, home: str, uid: str, now: int | None = None) -> dict | None:
    """The use was consumed but the action never ran: return it (once)."""
    return writes.give_back_contract_use(gclient.engine().select_graph(home), uid=uid,
                                         now=now_ms() if now is None else int(now))


def settle_use(*, home: str, uid: str, verdict: str, now: int | None = None) -> bool:
    return writes.contract_use_verdict(gclient.engine().select_graph(home), uid=uid, verdict=verdict,
                                       now=now_ms() if now is None else int(now))


def revoke(*, home: str, cid: str, by: str, now: int | None = None) -> bool:
    return writes.revoke_contract(gclient.engine().select_graph(home), cid=cid, by=by,
                                  now=now_ms() if now is None else int(now))


__all__ = ["CONTRACT_KINDS", "ContractRefused", "action_params", "params_hash", "family_of", "offer", "grant", "listing",
           "match_plan", "use", "give_back", "settle_use", "revoke", "one", "offer_row"]
