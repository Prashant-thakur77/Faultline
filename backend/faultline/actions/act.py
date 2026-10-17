"""The single action path: options → choose (exact action + plan hash) → approve (Approval +
idempotent Intent, one query) → execute (one gated write to GitHub) → verify (3-valued, second channel) →
write-back (W-WB-1 only if APPLIED, else W-WB-2) → re-read through a separate RO connection (`verified n/m`).

Choosing an option is not approving it: approval must quote the plan hash of the exact action the server rendered.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from falkordb import Graph

from ..graph import client as gclient
from ..graph import writes
from ..graph.ro import RO, canonical_json
from . import github as gh

INFRA_REPO = os.environ.get("DEMO_INFRA_REPO", "Prashant-thakur77/faultline-demo-infra")
FLAGS_PATH = "flags.json"
DEPLOYS_PATH = "deploys.json"


def lp(s: str) -> bytes:
    b = s.encode()
    return len(b).to_bytes(4, "big") + b


def idem_key(incident: str, action_type: str, args: dict) -> str:
    """sha256(lp(incident) + lp(action_type) + lp(canonical_json(args))) (Anchor-style, length-prefixed)."""
    return hashlib.sha256(lp(incident) + lp(action_type) + lp(canonical_json(args))).hexdigest()


def plan_hash(spec: dict) -> str:
    return hashlib.sha256(canonical_json(spec).encode()).hexdigest()


def lease_ms() -> int:
    """How long an intent lease lasts (weights.yaml actions.intent_lease_s); the holder renews it before every step."""
    from ..agent.weights import weights

    return int(weights()["actions"]["intent_lease_s"]) * 1000


def renew(c: "Ctx", aid: str) -> None:
    """Heartbeat for the execute job's lease; IntentNotPending when the intent was settled or taken over elsewhere."""
    if c.owner and not writes.renew_intent(c.g(), aid=aid, owner=c.owner, lease_ms=lease_ms()):
        raise writes.IntentNotPending(f"lease on {aid}'s intent lost: settled or taken over by another writer")


class NotExecuted(PermissionError):
    """execute() refused BEFORE touching anything outside the graph (a precondition failed)."""


class WorldMismatch(NotExecuted):
    """The data the incident was investigated on cannot be re-established (its fixture sources differ): neither
    execute nor verify can tie the repair to the incident's warehouse state, so a human decides (UNKNOWN)."""


@dataclass
class Ctx:
    tenant: str
    graph: str
    inc: str
    run: str
    owner: str | None = None  # the intent lease this writer holds (the API's execute job, or the reconciler)

    def g(self) -> Graph:
        return gclient.engine().select_graph(self.graph)

    def ro(self) -> RO:
        return RO(self.tenant, self.graph)


# ---------------------------------------------------------------------------------------------
# world seeding (simulated GitHub only): the demo infra repo mirrors the flags/deploys of the world
# ---------------------------------------------------------------------------------------------
def ensure_infra_repo(c: Ctx, hub: gh.GitHub) -> None:
    if not isinstance(hub, gh.SimGitHub) or hub.files.get(INFRA_REPO, {}).get("main"):
        return
    rows = c.ro().run("Q-FLAGS-1", {}).rows
    flags = {r["flag"]: {"state": r["state"], **({"cuts": [r["cuts_src"], r["cuts_dst"]]} if r["cuts_src"] else {})} for r in rows}
    hub.seed(INFRA_REPO, FLAGS_PATH, json.dumps({"flags": flags}, indent=2, sort_keys=True) + "\n")
    hub.seed(INFRA_REPO, DEPLOYS_PATH, json.dumps({"deploys": {}}, indent=2) + "\n")


# ---------------------------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------------------------
def set_world_flag(c: Ctx, hub: gh.GitHub, flag: str, state: str, why: str) -> None:
    """Scenario world change (not an agent action): a flag changed out of band, in the graph AND, in keyless
    mode, on the simulated infra repo's main. Real GitHub is never touched by scenario setup."""
    writes.set_flag_state(c.g(), flag=flag, state=state, why=why)
    if isinstance(hub, gh.SimGitHub) and hub.files.get(INFRA_REPO, {}).get("main", {}).get(FLAGS_PATH):
        doc = json.loads(hub.files[INFRA_REPO]["main"][FLAGS_PATH])
        doc["flags"][flag]["state"] = state
        hub.seed(INFRA_REPO, FLAGS_PATH, json.dumps(doc, indent=2, sort_keys=True) + "\n")


def _action(c: Ctx, aid: str) -> dict:
    """The action row of this incident's plan (read from the graph); unknown id → KeyError (HTTP 404/409)."""
    row = next((a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid), None)
    if row is None:
        raise KeyError(f"action {aid} is not part of {c.inc}'s plan")
    return row


def _main_flags(hub: gh.GitHub) -> tuple[dict | None, str]:
    """The flags as they are at GitHub main (the system under observation), or None + why it could not be read."""
    try:
        main, _ = hub.get_file(INFRA_REPO, FLAGS_PATH, "main")
        return json.loads(main).get("flags", {}), ""
    except gh.GitHubError as e:
        from ..public_errors import client_text

        return None, f"GitHub main could not be read ({client_text(e)})"


# ---------------------------------------------------------------------------------------------
# learned remediation ordering (remedy_stats / Q-REM-1): reorder only, never add, remove or enable
# ---------------------------------------------------------------------------------------------
BETA_PRIOR = 0.5  # (0+1)/(0+2): the Beta(1,1) mean Q-REM-1 smooths towards, i.e. what "no usable history" means
_KIND_WORD = {"flip_flag": "flag flip", "rollback_deploy": "rollback", "data_repair": "data repair"}


def _history_row(o: dict, by: dict[tuple[str, str], dict], min_n: int = 0) -> dict | None:
    """The most specific Q-REM-1 row with enough outcomes: the flag itself for flip_flag, else the kind ('*').
    A flag row thinner than `min_n` defers to the kind row instead of hiding it."""
    own = by.get((o["kind"], o["target"])) if o["kind"] == "flip_flag" else None
    if own is not None and int(own["n"]) >= min_n:
        return own
    return by.get((o["kind"], "*"))


FUTURE_RANK = {"contains": 0, "unknown": 1, "does_not_contain": 2}


def edge_key(u: str, v: str) -> str:
    """The futures key of one cut edge: `u|v`, or JSON when an id itself contains `|` (never ambiguous)."""
    return f"{u}|{v}" if "|" not in u + v else json.dumps([u, v])


def future_class(o: dict) -> int:
    """Where an option's predicted future puts it (futures, M14 #1): predicted to contain first, then unknown, then
    predicted not to contain. Within a class the static order and learned history decide: exposure is said, not
    ranked, so a removal predicted by assumption (rollback: residual 0 if the gate's cause is the cause) never outranks
    a measured prediction on a number it never measured. No future ⇒ unknown. Accepts an option as built (dict) or
    as read back from the graph (Q-ACT-1: JSON text)."""
    f = o.get("future") or {}
    if isinstance(f, str):
        f = json.loads(f)
    return FUTURE_RANK.get(f.get("predicted") or "unknown", 1)


def order_by_history(opts: list[dict], remedy: dict | None, min_n: int | None = None,
                     learned: dict | None = None) -> list[dict]:
    """Stable reorder of the ENABLED, production-changing options (not open_issue, which only tracks and stays after
    them; never the disabled ones) by the Beta-smoothed success rate Q-REM-1 computed. An option whose history has
    fewer than `remedy.min_n` outcomes keeps the prior mean. The result is a permutation of `opts` (same options, same
    enabled flags); the gate is not involved. History reorders only within one predicted-future class (`future_class`):
    a past success never lifts an option the futures predict will not contain above one they predict will. Every
    option gets `static_rank` (its place before learning) and, when history was used, `history` + a reason line.
    No history ⇒ the input order, unchanged.

    `learned` (M21: the learned_preferences tool result, read from the on-call home graph) blends in what the team
    chose: once the family has learn.pref_min_n recorded choices, each option's score is (1 - learn.w_pref) × its
    history rate + learn.w_pref × the team's Beta-smoothed preference for its kind, still only within one
    predicted-future class; an option against an ACTIVE guideline goes after the others of its class (and needs an
    explicit override to be approved: api._guideline_check). Every option is annotated (`learned`: the preference line,
    the guideline, a contract suggestion, `rank_without_learning`); nothing is added, removed, enabled or disabled."""
    from ..agent.weights import weights
    from ..memory import learning

    min_n = int(min_n if min_n is not None else weights()["remedy"]["min_n"])
    hist_ok = bool(remedy) and "error" not in (remedy or {})
    view = learning.plan_view(learned) if learned is not None else None
    if learned is not None:
        without = order_by_history([dict(o) for o in opts], remedy, min_n)   # the order learning would leave alone
        rank_without = {o["static_rank"]: i for i, o in enumerate(without, 1)}
    opts = [{**o, "static_rank": i, "history": None} for i, o in enumerate(opts, 1)]
    if not hist_ok and not (view and view.get("family")):
        return opts
    by = {(r["kind"], r["target"]): r for r in remedy.get("rows", [])} if hist_ok else {}
    basis = (remedy or {}).get("basis") or "past incidents sharing a symptom with this one"
    w_pref = float(weights()["learn"]["w_pref"])
    slots = [i for i, o in enumerate(opts) if o["enabled"] and o["kind"] != "open_issue"]
    rated = []
    for i in slots:
        o, row = opts[i], _history_row(opts[i], by, min_n)
        rate = BETA_PRIOR
        if row is not None and int(row["n"]) >= min_n:
            what = f"flag {o['target']} → off" if row["target"] != "*" else _KIND_WORD.get(o["kind"], o["kind"])
            line = (f"history: {what} worked {int(row['successes'])}/{int(row['n'])} times on {basis} "
                    f"(smoothed success {float(row['rate']):.2f})")
            opts[i] = {**o, "reason": f"{o['reason']}; {line}",
                       "history": {"successes": int(row["successes"]), "failures": int(row["failures"]),
                                   "n": int(row["n"]), "rate": round(float(row["rate"]), 4), "target": row["target"],
                                   "line": line}}
            rate = float(row["rate"])
        score, flagged = rate, False
        if view and view.get("family"):
            pref = learning.pref_of(view, o["kind"])
            if pref is not None:
                score = (1 - w_pref) * rate + w_pref * pref
            flagged = any(g["status"] == "active" for g in view["guides"].get(o["kind"]) or [])
        rated.append((i, score, flagged))
    # stable: ties keep the static order; neither history nor learning moves an option across a predicted-future class
    ordered = [opts[i] for i, _, _ in sorted(rated, key=lambda t: (future_class(opts[t[0]]), t[2], -t[1]))]
    out = list(opts)
    for slot, o in zip(slots, ordered):
        out[slot] = o
    if view and view.get("family"):
        scores = {i: sc for i, sc, _ in rated}
        for k, o in enumerate(out):
            ann = learning.annotate(o, view)
            if not ann:
                continue
            ann["rank_without_learning"] = rank_without.get(o["static_rank"])
            src = next((i for i in slots if opts[i]["static_rank"] == o["static_rank"]), None)
            if src is not None and view.get("applies"):
                ann["score"] = round(float(scores[src]), 4)
            lines = [x["line"] for x in (ann.get("preference"), ann.get("guideline"), ann.get("contract_suggestion")) if x]
            out[k] = {**o, "learned": ann, "reason": o["reason"] + "".join(f"; {ln}" for ln in lines)}
    return out


def remedy_summary(remedy: dict | None, options: list[dict]) -> dict:
    """What the learned ordering did, for the plan and the report: applied (history used), moved (order changed)."""
    if remedy is None:
        return {"applied": False, "moved": False, "note": "remedy history not consulted; static order"}
    if "error" in remedy:
        return {"applied": False, "moved": False, "note": f"remedy history unavailable ({remedy['error']}); static order kept"}
    used = [o for o in options if o.get("history")]
    ranked = [o for o in options if (o.get("learned") or {}).get("rank_without_learning") is not None]
    if ranked:   # learning also reordered (M21): history alone moved an option iff its order without learning differs
        moved = any(o["learned"]["rank_without_learning"] != o["static_rank"] for o in ranked)
    else:
        moved = [o["static_rank"] for o in options] != sorted(o["static_rank"] for o in options)
    if not used:
        return {"applied": False, "moved": False, "evidence_id": remedy.get("evidence_id"),
                "note": f"no history: no enabled fix on offer has ≥ min_n recorded outcomes on {remedy.get('basis')}; "
                        "static order kept (no-op)"}
    return {"applied": True, "moved": moved, "evidence_id": remedy.get("evidence_id"),
            "note": ("reordered by past outcomes: " if moved else "past outcomes agree with the static order: ")
            + "; ".join(f"{o['option']} {o['history']['successes']}/{o['history']['n']} ({o['history']['rate']:.2f})"
                        for o in used),
            "lines": [o["history"]["line"] for o in used]}


def build_options(c: Ctx, *, cause: str | None, cut: list[dict], hub: gh.GitHub, whatif: dict | None = None,
                  reviewers: list[str] | None = None, remedy: dict | None = None, futures: dict | None = None,
                  origin: str | None = None, symptoms: list[str] | None = None, learned: dict | None = None) -> list[dict]:
    """2–4 options from the fixed enum {flip_flag, rollback_deploy, data_repair, open_issue}; unavailable ones are
    listed disabled with a reason ("do not simulate them").

    Decisions that come from the graph and the world, not from text:
    * a flag lever is offered only for a min-cut edge (Q-CUT → Q-LEVER-1) AND only if the what-if branch says the
      cut contains the failure (WCC/BFS on GRAPH.COPY) AND only if GitHub main says the flag is still on AND only
      if its edge is on a failure path from the origin to this incident's own symptoms (Q-LEVER-PATH; a min-cut edge
      protects the entry set, which is not the same as touching what this incident is about);
    * the PR's reviewers are the top of `who_fixes` (HarmonicCentrality), bound into the plan hash;
    * `futures` (the futures tool result, Q-FUTURE-1 on one GRAPH.COPY branch per candidate) gives every option its
      predicted outcome: a flag its own min-cut edge's future, a rollback or data repair the origin-removed future,
      an issue the no-change future. The reason says it; the order puts predicted-to-contain first, and within a class
      keeps the static order. A predicted-not-to-contain option stays offered with its reason shown;
    * `remedy` (the remedy_stats tool result, Q-REM-1) only REORDERS the enabled actions within one predicted-future
      class (order_by_history);
    * `learned` (the learned_preferences tool result, M21) blends the team's recent choices into that order within
      the same class, flags options against an active guideline and annotates contract suggestions (order_by_history)."""
    opts = []
    reviewers = list(reviewers or [])[:3]
    flags, why_unread = _main_flags(hub)
    contains = (whatif or {}).get("verdict")

    def on_path(e: dict) -> bool:
        r = c.ro().run("Q-LEVER-PATH", {"origin": origin, "u": e["u"], "v": e["v"], "symptoms": list(symptoms or [])})
        return bool(r.rows and r.rows[0]["on_path"])
    for e in cut:
        levers = c.ro().run("Q-LEVER-1", {"u": e["u"], "v": e["v"]}).rows
        for lv in levers:
            main_state = (flags or {}).get(lv["flag"], {}).get("state") if flags is not None else None
            if flags is None:
                enabled, reason = False, f"{why_unread}; cannot tell whether {lv['flag']} is still on"
            elif main_state != "on":
                enabled, reason = False, f"flag {lv['flag']} is already {main_state or 'absent'} at GitHub main" + (
                    f" (graph mirror says {lv['state']}: drift)" if lv["state"] != main_state else "")
            elif contains == "does_not_contain":
                enabled, reason = False, f"what-if branch: cutting {e['u']} → {e['v']} does not protect the entry"
            elif origin and symptoms and not on_path(e):
                enabled, reason = False, (f"cuts {e['u']} → {e['v']}, which no failure path from {origin} to this "
                                          f"incident's symptoms ({', '.join(symptoms[:3])}) crosses: it would not "
                                          "change them (Q-LEVER-PATH)")
            elif cause is None:
                enabled, reason = False, ("no cause confirmed by the gate (abstention): only tracking is offered until a human "
                                          "confirms the origin")
            else:
                enabled = True
                reason = f"cuts {e['u']} → {e['v']} (min-cut edge, cut_cost {e['cut_cost']}); {lv['note']}" + (
                    "; what-if branch: contains the failure" if contains == "contains" else "")
            opts.append({"kind": "flip_flag", "option": f"flag {lv['flag']} → off", "target": lv["flag"], "enabled": enabled,
                         "reason": reason, "args": {"repo": INFRA_REPO, "path": FLAGS_PATH, "flag": lv["flag"],
                                                    "state": "off", "reviewers": reviewers}, "_edge": (e["u"], e["v"])})
        if not levers:
            opts.append({"kind": "flip_flag", "option": f"cut {e['u']} → {e['v']}", "target": e["v"], "enabled": False,
                         "reason": f"no flag cuts {e['u']} → {e['v']} ({e['domain']} edge): not offered, not simulated",
                         "args": {}})
    detail = c.ro().run("Q-CHANGE-2", {"id": cause}).rows if cause else []
    if detail and detail[0]["kind"] in ("deploy", "config"):
        opts.append({"kind": "rollback_deploy", "option": f"roll back {cause}", "target": cause, "enabled": True,
                     "reason": f"revert {detail[0]['title'] or cause} on {detail[0]['target']} (removes the cause; slower than a flag)",
                     "args": {"repo": INFRA_REPO, "path": DEPLOYS_PATH, "service": detail[0]["target"], "revert": cause,
                              "reviewers": reviewers}})
    elif detail and detail[0]["kind"] == "data_cutover":
        opts.append({"kind": "data_repair", "option": f"repair the transform affected by {cause}", "target": cause,
                     "enabled": False, "reason": "needs a proposed transform patch (the specialist proposes one in live mode; "
                     "keyless runs cannot author SQL); call propose_data_repair to enable", "args": {}})
    subject = cause or "the inferred upstream origin (unconfirmed)"
    opts.append({"kind": "open_issue", "option": f"open an issue for {subject}", "target": cause or c.inc, "enabled": True,
                 "reason": "hand the cause to the owner team (no change to production; does not resolve the incident)",
                 "args": {"repo": INFRA_REPO, "title": f"Incident {c.inc}: {subject}", "reviewers": reviewers}})
    fmap = {x["key"]: x for x in (futures or {}).get("rows", [])}
    for o in opts:
        edge = o.pop("_edge", None)
        key = ((edge_key(*edge) if edge else None) if o["kind"] == "flip_flag" else
               "remove_origin" if o["kind"] in ("rollback_deploy", "data_repair") else "no_change")
        f = fmap.get(key) if key else None
        if f is None or not o["args"]:  # no future read, or an edge with no lever (not offered, not simulated)
            continue
        o["future"] = {"key": key, "predicted": f["predicted"], "line": f["line"], "exposed": f.get("exposed") or [],
                       "assumed": bool(f.get("assumed")), "evidence_id": (futures or {}).get("evidence_id")}
        o["reason"] += f"; future: {f['line']}" + (f"; leaves {', '.join(f['exposed'])} exposed" if f.get("exposed") else "")
    # keep the list short but never lose a usable option: enabled options first, then ONE note for cut edges that have
    # no lever (merged), then the rest of the disabled ones; open_issue (tracking) is always kept
    no_lever = [o for o in opts if o["kind"] == "flip_flag" and not o["enabled"] and not o["args"]]
    if len(no_lever) > 1:
        merged = dict(no_lever[0])
        merged.update(option=f"cut {len(no_lever)} min-cut edges", target=no_lever[0]["target"],
                      reason="no flag cuts these min-cut edges: " + "; ".join(o["option"].removeprefix("cut ") for o in no_lever)
                      + " (not offered, not simulated)")
        opts = [o for o in opts if o not in no_lever] + [merged]
    opts = sorted(opts, key=lambda o: (not o["enabled"], o["kind"] == "open_issue", future_class(o)))
    keep = [o for o in opts if o["kind"] != "open_issue"][:3] + [o for o in opts if o["kind"] == "open_issue"][:1]
    opts = sorted(keep, key=lambda o: (not o["enabled"], o["kind"] == "open_issue", future_class(o)))
    opts = order_by_history(opts, remedy, learned=learned)  # learned ordering: a permutation of the enabled actions only
    out = []
    for i, o in enumerate(opts[:4], 1):
        aid = f"act-{c.inc}-{i}"
        writes.record_option(c.g(), inc=c.inc, aid=aid, kind=o["kind"], option=o["option"], enabled=o["enabled"],
                             reason=o["reason"], target=o["target"], preview=o["args"], future=o.get("future"),
                             learned=o.get("learned"), rank=i)
        out.append({"id": aid, **o})
    return out


# ---------------------------------------------------------------------------------------------
# choose → exact action
# ---------------------------------------------------------------------------------------------
def render(c: Ctx, option: dict, hub: gh.GitHub) -> dict:
    """The exact action the human approves: repo, branch faultline/fix-<idem8>, file diff, commit message, rollback."""
    args = json.loads(option["preview"]) if isinstance(option.get("preview"), str) else option.get("args", {})
    kind = option["kind"]
    idem = idem_key(c.inc, kind, args)
    branch = f"{gh.FIX_PREFIX}{idem[:8]}"
    spec: dict = {"kind": kind, "incident": c.inc, "args": args, "branch": branch, "idem": idem}
    if kind == "flip_flag":
        before, _ = hub.get_file(args["repo"], args["path"])
        doc = json.loads(before)
        doc["flags"][args["flag"]]["state"] = args["state"]
        after = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        spec.update(file=args["path"], before=before, after=after,
                    commit=f"fix: turn {args['flag']} {args['state']} (contain {c.inc})\n\nFaultline-Idem: {idem}",
                    rollback=f"set flags.{args['flag']}.state back to 'on' in {args['path']}")
        _pr_body(spec, c, args)
    elif kind == "rollback_deploy":
        before, _ = hub.get_file(args["repo"], args["path"])
        doc = json.loads(before)
        doc.setdefault("deploys", {})[args["service"]] = {"reverted": args["revert"]}
        after = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        spec.update(file=args["path"], before=before, after=after,
                    commit=f"revert: roll back {args['revert']} on {args['service']} ({c.inc})\n\nFaultline-Idem: {idem}",
                    rollback=f"re-deploy {args['revert']}")
        _pr_body(spec, c, args)
    elif kind == "data_repair":
        spec.update(file=args["file"], before=args["before"], after=args["after"], diff=args["diff"],
                    commit=f"fix(data): {args['reasoning'][:60]} ({c.inc})\n\nFaultline-Idem: {idem}",
                    rollback=f"restore {args['file']} to the plan's `before` (or its pristine copy) and rebuild the warehouse")
    elif kind == "open_issue":
        who = ", ".join(args.get("reviewers") or []) or "the owner team"
        spec.update(title=args["title"], body=f"Opened by Faultline for {c.inc}. Suggested owners: {who}.\n\nFaultline-Idem: {idem}")
    if spec.get("before") is not None and spec.get("before") == spec.get("after"):
        raise ValueError(f"{kind} would change nothing ({spec.get('file')} already in that state at main): not offered")
    spec["plan_hash"] = plan_hash({k: v for k, v in spec.items() if k != "plan_hash"})
    return spec


def _pr_body(spec: dict, c: Ctx, args: dict) -> None:
    who = ", ".join(args.get("reviewers") or [])
    spec["pr_body"] = (f"Approved in Faultline ({c.inc}).\n\n" + (f"Suggested reviewers (who_fixes): {who}\n\n" if who else "")
                       + f"Rollback: {spec['rollback']}\n\nFaultline-Idem: {spec['idem']}")


def choose(c: Ctx, aid: str, hub: gh.GitHub) -> dict:
    rows = [a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid]
    if not rows or not rows[0]["enabled"]:
        raise ValueError(f"option {aid} is not available")
    spec = render(c, rows[0], hub)
    if not writes.choose_action(c.g(), inc=c.inc, aid=aid, spec=spec, plan_hash=spec["plan_hash"], idem=spec["idem"]):
        raise ValueError("incident is not awaiting approval")
    return spec


# ---------------------------------------------------------------------------------------------
# execute → verify → write-back
# ---------------------------------------------------------------------------------------------
def execute(c: Ctx, aid: str, hub: gh.GitHub) -> dict:
    """The only tool that mutates the outside world. Preconditions are enforced by the approval query (plan hash,
    stage) and here: only the run that created the intent proceeds; only faultline/fix-* branches are touched."""
    rows = c.ro().run("Q-ACT-INTENT", {"inc": c.inc, "aid": aid}).rows
    if not rows:
        raise PermissionError(f"action {aid} has no approved intent")
    act = rows[0]
    spec = json.loads(act["spec"] or "{}")
    if act["status"] != "approved":
        raise PermissionError(f"action {aid} is not approved (status {act['status']})")
    if act["intent_state"] != "PENDING":
        raise PermissionError(f"intent for {aid} is {act['intent_state']}, not PENDING")
    if act["intent_run"] != c.run:
        raise PermissionError(f"intent for {aid} belongs to run {act['intent_run']}, not {c.run}")
    if c.owner and act.get("lease_by") != c.owner:  # the reconciler took it over: never touch the outside world
        raise writes.IntentNotPending(f"intent for {aid} is leased by {act.get('lease_by')}, not this job")
    if c.owner and not act.get("lease_live"):  # fenced: an expired lease may be taken over at any moment (engine clock)
        raise writes.IntentNotPending(f"the lease on {aid}'s intent expired before execute; not touching the outside world")
    if plan_hash({k: v for k, v in spec.items() if k != "plan_hash"}) != act["plan_hash"]:
        raise PermissionError(f"stored action for {aid} no longer matches its approved plan hash")
    if spec["kind"] in ("flip_flag", "rollback_deploy"):
        pr = hub.find_pr(spec["args"]["repo"], spec["branch"])  # idempotent: reuse a PR for the same idem key
        if pr is None:
            main, _ = hub.get_file(spec["args"]["repo"], spec["file"], "main")
            if main != spec["before"]:  # the world moved since the human approved this exact diff
                raise PermissionError(f"{spec['file']} changed at main since approval; re-plan (stale diff refused)")
            if not hub.branch_exists(spec["args"]["repo"], spec["branch"]):
                hub.create_branch(spec["args"]["repo"], spec["branch"])
            hub.put_file(spec["args"]["repo"], spec["branch"], spec["file"], spec["after"], spec["commit"])
            pr = hub.open_pr(spec["args"]["repo"], spec["branch"], spec["commit"].splitlines()[0], spec["pr_body"])
        merge = hub.merge_pr(spec["args"]["repo"], pr["number"]) if pr.get("state") != "merged" else "already-merged"
        ref = pr["url"]
        detail = {"pr": pr, "merge": merge, "served_by": hub.label}
    elif spec["kind"] == "data_repair":
        from .. import repair
        from ..scenario import WAREHOUSE

        with WAREHOUSE.exclusive():  # re-entrant: the API job already holds it across execute + verify
            restore_fixture(spec)  # the incident's own data, or WorldMismatch before anything is touched
            cur = repair._resolve_transform(spec["file"]).read_text()
            if cur not in (spec["before"], spec["after"]):  # someone changed the file since the plan was approved
                raise NotExecuted(f"{spec['file']} changed since approval; re-plan (plan hash no longer matches the world)")
            try:
                patch = repair.propose_patch(spec["file"], spec["after"], spec["args"]["reasoning"]) \
                    if cur != spec["after"] else None
            except ValueError as e:  # the SQL validator (or an identical file): nothing was touched
                raise NotExecuted(f"the approved transform was refused: {e}") from None
            if patch is not None:
                repair.apply_patch(patch, spec["after"])
        ref, detail = f"local:{spec['file']}", {"applied": patch is not None, "served_by": "local transform repair (allowlisted)",
                                                "fixture": spec["args"].get("fixture")}
    else:
        issue = hub.find_issue(spec["args"]["repo"], f"Faultline-Idem: {spec['idem']}") or \
            hub.create_issue(spec["args"]["repo"], spec["title"], spec["body"])
        ref, detail = issue["url"], {"issue": issue, "served_by": hub.label}
    _chaos_pause("after_merge_before_record")  # the crash window: changed at GitHub, not yet recorded in the graph
    writes.record_execution(c.g(), aid=aid, ref=ref, detail=detail, owner=c.owner)
    _chaos_pause("after_execute")
    return {"external_ref": ref, **detail}


CHAOS_POINTS = ("after_merge_before_record", "after_execute")


def chaos_allowed() -> bool:
    """The chaos hooks never activate on the public demo or against real GitHub (a pause there would hold a real
    change half-done)."""
    from ..config import settings

    return not settings.faultline_public and not gh.is_real()


def _chaos_pause(point: str) -> None:
    """Test hook for the SIGKILL chaos test only (evals/chaos.py): with FAULTLINE_CHAOS_PAUSE=<point> this process
    writes FAULTLINE_CHAOS_MARKER and stops here, so the test can kill -9 it there. Points: after_merge_before_record
    (the PR is merged at GitHub, the graph has no record of it yet) and after_execute (recorded, not verified). Off
    unless the environment variable is set; never set by the product or the deploy config; refused (logged, no pause)
    when FAULTLINE_PUBLIC is on or real GitHub is configured."""
    if os.environ.get("FAULTLINE_CHAOS_PAUSE") != point:
        return
    if not chaos_allowed():
        import logging

        logging.getLogger("faultline.chaos").error("FAULTLINE_CHAOS_PAUSE=%s refused: public mode or real GitHub", point)
        return
    import time
    from pathlib import Path

    if os.environ.get("FAULTLINE_CHAOS_MARKER"):
        Path(os.environ["FAULTLINE_CHAOS_MARKER"]).write_text(point)
    time.sleep(float(os.environ.get("FAULTLINE_CHAOS_SLEEP_S", "600")))


def allowances(c: Ctx, targets: list[str], *, onset_ms: int, since: int, until: int,
               cut_edges: set[tuple[str, str]]) -> dict:
    """An upper bound on the share of each symptom that OTHER open incidents still own (Q-VERIFY-ALLOW, read-only),
    under the telemetry model (sim/telemetry.py): a node's excess rises by at most the sum, over its in-edges, of
    cap × the source's excess, so an origin's share at a symptom is at most its measured excess × its path transfer,
    the sum over its uncut PROPAGATES_TO paths of the product of the caps (the bottleneck max flow is not a bound:
    it over-states multi-hop leaks and counts cut edges).
      * qualifying origins: other open incidents' confirmed origins (a different change on a different component
        than this incident's confirmed causes) that this incident's own origins do not reach (algo.BFS): an origin
        downstream of our fault carries our own leak in its excess, so it allows nothing;
      * several origins never count shared capacity twice: a path through another qualifying origin is that
        origin's (its measured excess already holds what flows through it), and incidents blaming one origin are
        one row; so the per-origin rows of a symptom are summed;
      * unknown (null) allows nothing and is reported: an unmeasured excess, an edge without cap, > 1000 paths.
    No confirmed cause on this incident, or no qualifying origin ⇒ every allowance is 0."""
    from ..agent.state import TERMINALS
    from ..agent.weights import weights

    iw = weights()["intake"]  # the same baseline span and gap the carry rule (Q-STORM-EDGES / Q-PRIMARY-1) uses
    params = {"inc": c.inc, "symptoms": sorted(set(targets)), "terminal": sorted(s.value for s in TERMINALS),
              "cuts": sorted(f"{u}|{v}" for u, v in cut_edges), "since": since, "until": until,
              "base_since": onset_ms - int(iw["baseline_min"]) * 60_000,
              "base_until": onset_ms - int(iw["baseline_gap_min"]) * 60_000}
    res = c.ro().run("Q-VERIFY-ALLOW", params)
    if res.truncated:  # a partial list would understate what other incidents own: fail loudly (→ UNKNOWN upstream)
        from ..graph.errors import GraphError

        raise GraphError("Q-VERIFY-ALLOW truncated: too many concurrent incidents to read their allowances")
    per: dict[str, dict] = {t: {"allowance": 0.0, "from": [], "unmeasured": []} for t in targets}
    for r in res.rows:
        slot = per.setdefault(r["symptom"], {"allowance": 0.0, "from": [], "unmeasured": []})
        if r["allowance"] is None:
            why = ("excess unmeasured" if r["excess"] is None else
                   "more paths than the bound reads" if (r["paths"] or 0) > 1000 else "an edge without cap")
            slot["unmeasured"].append({"incidents": r["incidents"], "origin": r["origin"], "why": why})
            continue
        slot["allowance"] = round(min(1.0, slot["allowance"] + float(r["allowance"])), 6)
        slot["from"].append({"incident": r["incident"], "incidents": r["incidents"], "cause": r["cause"],
                             "causes": r["causes"], "origin": r["origin"], "hops": r["hops"], "paths": r["paths"],
                             "transfer": round(float(r["transfer"]), 6), "excess": round(float(r["excess"]), 6),
                             "allowance": round(float(r["allowance"]), 6)})
    return {"template": res.template_id, "cypher": res.cypher, "params": params, "digest": res.digest,
            "rows": res.rows, "per_symptom": per,
            "note": ("no other open incident's confirmed origin reaches these symptoms: allowance 0" if not res.rows else
                     "symptom error other open incidents can still cause is allowed: their origin's measured excess × "
                     "its path transfer over uncut edges (sum of cap products), an upper bound under the telemetry model")}


def verify(c: Ctx, aid: str, hub: gh.GitHub, *, symptom: str | list[str], onset_ms: int, effects: list, at_ms: int,
           protect: list[str] | None = None, world_seed: int = 42, world_graph: str | None = None) -> dict:
    """3-valued verification through a second channel:
       channel 1: the desired state at the default-branch HEAD (GitHub REST re-read, not the API call we made);
       channel 2: the world: telemetry generated AFTER the action from the state at main. EVERY symptom must be back
                  in band for 3 minutes, and nothing protected (collateral) may be out of band. "In band" leaves room
                  only for an upper bound on the share of a symptom that OTHER open incidents still own (`allowances`,
                  Q-VERIFY-ALLOW: their origin's excess × its path transfer over uncut edges); with no other open
                  incident it is 0 and the check is exactly the plain band. The allowance is recorded in the channel and named in
                  the explanation whenever it is used.
       APPLIED = both; NOT_APPLIED = either says no; UNKNOWN = a channel could not be read (explanation mandatory).
       open_issue: the issue is found again by its idem key (it tracks; it does not fix).
       `world_seed`: the simulated world's seed (its services' base error rates; scenario `seed`, default 42).
       `world_graph`: where the simulated world's topology lives when it is NOT the graph the product reads (evals
       that make the graph wrong on purpose); default: the same graph (the demo's world)."""
    from ..agent.datatools import band_from, in_band
    from ..agent.weights import weights
    from ..sim.telemetry import simulate

    act = _action(c, aid)
    spec = json.loads(act["spec"])
    targets = [symptom] if isinstance(symptom, str) else list(symptom)
    collateral = [p for p in (protect or []) if p not in targets]
    channels: dict = {}
    observed = None  # did the containment hold on the symptoms alone (for the futures record; never the verdict)
    iw = weights()["intake"]  # the baseline span and gap Q-FUTURE-1 and the carry rule use (one setting, no drift)
    base_since = onset_ms - int(iw["baseline_min"]) * 60_000
    base_until = onset_ms - int(iw["baseline_gap_min"]) * 60_000
    try:
        if spec["kind"] == "open_issue":
            found = hub.find_issue(spec["args"]["repo"], f"Faultline-Idem: {spec['idem']}")
            channels["github_issue"] = {"ok": bool(found), "served_by": hub.label}
            verdict, why = ("APPLIED", f"issue {found['url']} exists with the idem key (tracking only; no production change)") \
                if found else ("NOT_APPLIED", "no issue carries this action's idem key")
            writes.record_verdict(c.g(), aid=aid, verdict=verdict, why=why, channels=channels, owner=c.owner)
            return {"verdict": verdict, "explanation": why, "channels": channels}
        if spec["kind"] == "data_repair":
            return _verify_data_repair(c, aid, spec)
        main, _ = hub.get_file(spec["args"]["repo"], spec["file"], "main")
        doc = json.loads(main)
        if spec["kind"] == "flip_flag":
            ok1 = doc["flags"][spec["args"]["flag"]]["state"] == spec["args"]["state"]
        else:
            ok1 = doc.get("deploys", {}).get(spec["args"]["service"], {}).get("reverted") == spec["args"]["revert"]
        channels["github_main"] = {"ok": ok1, "served_by": hub.label}
        cut_edges = {tuple(f["cuts"]) for f in doc.get("flags", {}).values() if f.get("state") == "off" and f.get("cuts")}
        reverted = {v.get("reverted") for v in doc.get("deploys", {}).values()}
        # a rollback removes only the effects that change caused (rolling back the wrong deploy fixes nothing)
        live = [e for e in effects if not (getattr(e, "change", None) and e.change in reverted)]
        simulate(c.g(), c.ro(), onset_ms=onset_ms, effects=live, cut_edges=cut_edges, start_ms=at_ms + 60_000, minutes=3,
                 seed=int(at_ms % 10_000), base_seed=int(world_seed),  # the world's base rates, fresh noise
                 topology=RO(c.tenant, world_graph) if world_graph else None)
        allow = allowances(c, targets, onset_ms=onset_ms, since=at_ms + 60_000, until=at_ms + 4 * 60_000,
                           cut_edges=cut_edges)
        bad: list[str] = []
        used: list[str] = []
        per: dict = {}
        for t in targets + collateral:
            rows = c.ro().run("Q-MW-1", {"target": t, "metric": "error_rate", "since": at_ms + 60_000, "until": at_ms + 4 * 60_000}).rows
            base_vals = [r["value"] for r in c.ro().run("Q-MW-1", {"target": t, "metric": "error_rate",
                                                                   "since": base_since, "until": base_until}).rows]
            base = sum(base_vals) / len(base_vals) if base_vals else 0.0
            band = band_from(base_vals)
            after = [r["value"] for r in rows]
            if t in collateral and not base_vals and not after:  # no error-rate telemetry on it (e.g. a KPI): noted
                per[t] = {"ok": None, "note": "no error_rate telemetry; not a collateral signal", "collateral": True}
                continue
            if t in collateral:  # collateral = the ACTION made a protected node worse than it was just before it
                during = [r["value"] for r in c.ro().run("Q-MW-1", {"target": t, "metric": "error_rate", "since": onset_ms,
                                                                     "until": at_ms + 1}).rows]
                ref = max(during) if during else base
                ok = len(after) == 3 and all(v <= ref * 1.1 + 0.002 for v in after)
                per[t] = {"ok": ok, "after": after, "before_action_max": round(ref, 5), "collateral": True}
                if not ok:
                    bad.append(t)
                continue
            a = allow["per_symptom"][t]
            share = a["allowance"]  # what other open incidents still own of this symptom (0.0 when none)
            ok = len(after) == 3 and all(in_band(v, base, band, share) for v in after)
            per[t] = {"ok": ok, "after": after, "baseline": round(base, 5), "band": band, "collateral": t in collateral}
            if share or a["unmeasured"]:  # visible whenever another incident is involved; absent (unchanged) otherwise
                per[t].update(allowance=share, allowance_from=a["from"], allowance_unmeasured=a["unmeasured"],
                              in_plain_band=len(after) == 3 and all(in_band(v, base, band) for v in after))
                if ok and not per[t]["in_plain_band"]:
                    used.append(t)
            if not ok:
                bad.append(t)
        ok2 = not bad
        channels["telemetry"] = {"ok": ok2, "targets": per, "allowance": allow}
        # what the futures predicted is the symptoms' own band, without another incident's allowance; collateral and
        # a change missing at main are not containment outcomes
        plain = [per[t].get("in_plain_band", per[t]["ok"]) for t in targets]
        if ok1 and plain and None not in plain:
            observed = "contains" if all(plain) else "does_not_contain"
        if ok1 and ok2:
            verdict = "APPLIED"
            why = (f"{spec['file']} at main HEAD has the change; {', '.join(targets)} back in band for 3 minutes"
                   + (f"; no collateral on {', '.join(t for t in collateral if per[t]['ok'])}"
                      if any(per[t]["ok"] for t in collateral) else "")
                   + ("".join(f"; {t} within band + {per[t]['allowance']:.4f} that open incident(s) can still cause: "
                              + ", ".join(f"{', '.join(x['incidents'])} (origin {x['origin']}, path transfer "
                                          f"{x['transfer']:.3g} × excess {x['excess']:.3g})" for x in per[t]["allowance_from"])
                              + " (Q-VERIFY-ALLOW)" for t in used)))
        else:
            verdict = "NOT_APPLIED"
            why = ("change not present at main HEAD" if not ok1 else
                   f"still out of band after the change: {', '.join(bad)}"
                   + (" (collateral)" if set(bad) & set(collateral) else "")
                   + "".join(f"; {t} exceeds band + {per[t]['allowance']:.4f} that open incident(s) "
                             f"{', '.join(i for x in per[t]['allowance_from'] for i in x['incidents'])} can still cause (Q-VERIFY-ALLOW)"
                             for t in bad if per[t].get("allowance")))
    except gh.GitHubError as e:  # timeouts AND any other GitHub failure: we cannot tell → UNKNOWN, escalate
        from ..public_errors import client_text

        text = client_text(e)
        verdict, why = "UNKNOWN", f"GitHub could not be read to confirm the change at main HEAD ({text}); escalated to a human"
        channels["github_main"] = {"ok": None, "error": text}
    prediction = prediction_outcome(act.get("future"), spec["kind"], observed)
    if prediction:
        channels["prediction"] = prediction
    writes.record_verdict(c.g(), aid=aid, verdict=verdict, why=why, channels=channels, owner=c.owner)
    return {"verdict": verdict, "explanation": why, "channels": channels}


def prediction_outcome(future: str | dict | None, kind: str, observed: str | None) -> dict | None:
    """Did the option's predicted future (futures tool, recorded on the Action) come true? Recorded beside the
    channels, never one of them: the verdict is decided by GitHub main and telemetry alone. `observed` is the
    symptoms' own band after the change (verify computes it only when the change is at main HEAD; None otherwise,
    and for UNKNOWN). An issue only tracks, so it is never compared."""
    f = json.loads(future) if isinstance(future, str) else future
    if not f or kind == "open_issue" or observed is None or f.get("predicted") == "unknown":
        return None
    return {"predicted": f["predicted"], "observed": observed, "agrees": f["predicted"] == observed,
            "assumed": bool(f.get("assumed")), "key": f.get("key"), "evidence_id": f.get("evidence_id")}


def propose_data_repair(c: Ctx, *, file: str, new_content: str, reasoning: str) -> dict:
    """Record a proposed transform patch as the data_repair option's exact arguments (allowlisted transforms only;
    the diff is computed here, so the displayed patch is the patch that runs). Enables the option."""
    from .. import repair

    patch = repair.propose_patch(file, new_content, reasoning)
    before = repair._resolve_transform(file).read_text()
    after = new_content if new_content.endswith("\n") else new_content + "\n"
    rows = [a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["kind"] == "data_repair"]
    if not rows:
        raise ValueError(f"{c.inc} has no data_repair option (not a data incident)")
    from .. import warehouse

    # the warehouse state this incident was investigated on (mode + sources digest), bound into the plan hash: execute
    # and verify re-establish it, and a repair is never verified against another run's data (review round 5, M2)
    args = {"file": file, "before": before, "after": after, "diff": patch.diff, "reasoning": reasoning[:500],
            "fixture": warehouse.fixture_state()}
    writes.record_option(c.g(), inc=c.inc, aid=rows[0]["id"], kind="data_repair", option=rows[0]["option"], enabled=True,
                         reason=f"proposed patch to {file}: {reasoning[:200]}", target=rows[0]["target"], preview=args,
                         keep_future=True)
    return {"id": rows[0]["id"], **args}


def restore_fixture(spec: dict) -> dict:
    """Re-establish the warehouse fixture this data repair's incident was investigated on (the plan's recorded mode and
    sources digest), keeping the transforms as they are (the repair's own patch must stay). Caller holds
    WAREHOUSE.exclusive(). WorldMismatch when the plan recorded no fixture or the regenerated sources differ."""
    from .. import warehouse
    from ..scenario import WAREHOUSE, set_pipeline_mode

    if not WAREHOUSE.held_alone_by_me():
        raise RuntimeError("restore_fixture needs the warehouse's exclusive hold")
    fx = (spec.get("args") or {}).get("fixture") or {}
    if not fx.get("mode") or not fx.get("sources_sha256"):
        raise WorldMismatch("the plan recorded no warehouse fixture (mode + sources digest), so the repair cannot be tied "
                            "to the incident's data; re-propose it")
    if warehouse.fixture_state() != {"mode": fx["mode"], "sources_sha256": fx["sources_sha256"]}:
        set_pipeline_mode(fx["mode"], restore_transforms=False, rebuild=False)
    now = warehouse.fixture_state()
    if now["sources_sha256"] != fx["sources_sha256"]:
        raise WorldMismatch(f"the warehouse sources for mode {fx['mode']!r} no longer match the ones the incident was "
                            f"investigated on (digest {now['sources_sha256'][:12]} vs {fx['sources_sha256'][:12]})")
    return now


def _verify_data_repair(c: Ctx, aid: str, spec: dict) -> dict:
    """data_repair, 3-valued, tied to the incident's own warehouse state (review round 5, M2): under the warehouse's
    exclusive hold, the fixture the plan recorded is re-established first (mode + sources digest; a digest that still
    differs is UNKNOWN, escalated). Channel 1 re-reads the transform on disk; channel 2 is the world: rebuild the
    warehouse, run the invariant suite and recompute the KPI. A failed repair is reverted to the plan's `before` and the
    warehouse rebuilt (NOT_APPLIED); an UNKNOWN one is left applied and marked (repair.mark_unverified) for the
    reconciler, until the next mode switch or re-arm restores the pristine transform."""
    from .. import repair
    from ..scenario import WAREHOUSE

    channels: dict = {}

    def unknown(why: str) -> dict:
        try:
            repair.mark_unverified(spec["file"], {"incident": c.inc, "action": aid, "idem": spec.get("idem"), "why": why})
        except Exception:  # noqa: BLE001 - the marker is a courtesy; the verdict below is what counts
            pass
        writes.record_verdict(c.g(), aid=aid, verdict="UNKNOWN", why=why, channels=channels, owner=c.owner)
        return {"verdict": "UNKNOWN", "explanation": why, "channels": channels}

    with WAREHOUSE.exclusive():
        try:
            fx = restore_fixture(spec)
            channels["fixture"] = {"ok": True, "mode": fx["mode"], "sources_sha256": fx["sources_sha256"][:16]}
        except WorldMismatch as e:
            channels["fixture"] = {"ok": None, "reason": str(e)[:300]}
            return unknown(f"cannot tie verification to the incident's warehouse state: {e}; escalated to a human")
        except Exception as e:  # noqa: BLE001 - the fixture could not be rebuilt: we cannot tell
            from ..public_errors import client_text

            channels["fixture"] = {"ok": None, "error": client_text(e)}
            return unknown(f"the incident's warehouse fixture could not be re-established ({client_text(e)}); "
                           "escalated to a human")
        on_disk = repair._resolve_transform(spec["file"]).read_text()
        ok1 = on_disk == spec["after"]
        channels["file"] = {"ok": ok1, "path": spec["file"]}
        try:
            report, snap, ok2 = repair.verify_repair()
        except Exception as e:  # noqa: BLE001 - the rebuild could not run: we cannot tell
            from ..public_errors import client_text

            channels["warehouse"] = {"ok": None, "error": client_text(e)}
            return unknown(f"warehouse rebuild/invariants could not run ({client_text(e)}); escalated to a human")
        channels["warehouse"] = {"ok": ok2, "invariants": f"{report.passed}/{report.total}",
                                 "kpi_anomaly_ratio": round(snap.anomaly_ratio, 4), "kpi_status": snap.status,
                                 "mode": fx["mode"]}
        if ok1 and ok2:
            verdict = "APPLIED"
            why = (f"{spec['file']} carries the patch; on the incident's own data (mode {fx['mode']}, sources "
                   f"{fx['sources_sha256'][:12]}) the rebuild passed {report.passed}/{report.total} invariants and the KPI "
                   f"anomaly ratio is {snap.anomaly_ratio:.3f} (inside 0.8–1.3)")
        else:
            verdict = "NOT_APPLIED"
            why = ("patched transform not on disk" if not ok1 else
                   f"invariants {report.passed}/{report.total}, KPI anomaly ratio {snap.anomaly_ratio:.3f} on the "
                   f"incident's own data (mode {fx['mode']}): repair did not fix the symptom; reverted")
            if ok1:
                rv = repair.revert_to(spec["file"], before=spec["before"], after=spec["after"])
                channels["revert"] = rv
                if rv.get("state") == "reverted" and not rv.get("rebuilt"):
                    why += " (the rebuild after the revert failed; the warehouse still holds the patched build)"
    writes.record_verdict(c.g(), aid=aid, verdict=verdict, why=why, channels=channels, owner=c.owner)
    return {"verdict": verdict, "explanation": why, "channels": channels}


def precedents_for(c: Ctx, cause: str) -> list[str]:
    """Recalled incidents whose own cause changed the same component as this one (Q-MEM-2, read from the graph)."""
    target = (c.ro().run("Q-CHANGE-1", {"id": cause}).rows or [{"target": cause}])[0]["target"]
    return [r["id"] for r in c.ro().run("Q-MEM-2", {"inc": c.inc, "target": target}).rows]


def write_back(c: Ctx, aid: str, *, cause: str, confident: bool, precedents: list[str] | None = None) -> dict:
    act = _action(c, aid)
    if act["verdict"] == "APPLIED" and act["kind"] == "open_issue":
        return {"written": None, "tracked": writes.write_back_tracked(c.g(), inc=c.inc, aid=aid, owner=c.owner),
                "verified": None}
    if act["verdict"] == "APPLIED":
        precedents = precedents_for(c, cause) if precedents is None else precedents
        summary = f"{cause} caused {c.inc}; contained by {act['option']} ({act['external_ref']})."
        # M20 #5: the write-back and WAITAOF share ONE connection, so WAITAOF waits for exactly this write to be fsynced
        with gclient.engine_session(c.graph) as (g1, conn):
            ids = writes.write_back_applied(g1, inc=c.inc, cause=cause, aid=aid, confident=confident, summary=summary,
                                            pmurl=f"docs/postmortems/pm-{c.inc}.md", precedents=precedents, owner=c.owner)
            durable = gclient.wait_aof(conn, timeout_ms=_waitaof_ms())
        try:  # the write is committed; a failed re-read is reported, never turned into a failure of the write
            check = verify_writeback(c, aid=aid, cause=cause, ids=ids)
        except Exception as e:  # noqa: BLE001
            from ..public_errors import client_text

            check = {"verified": "0/7", "checks": {}, "reread_error": client_text(e)}
        if not durable["ok"]:  # not confirmed on disk: VERIFY does not count it (UNKNOWN → a human checks, never RESOLVED)
            check = {**check, "verified": f"0/{len(check.get('checks') or {}) or 7}",
                     "reread_error": f"durability UNKNOWN: FalkorDB did not confirm the write-back on disk (WAITAOF: "
                                     f"{durable.get('error') or 'not synced'}); escalated to a human"}
        return {"written": ids, "precedents": precedents, **check, "durable": durable}
    stage = "UNKNOWN_ESCALATED" if act["verdict"] == "UNKNOWN" else "AWAITING_APPROVAL"
    out = writes.write_back_not_applied(c.g(), inc=c.inc, aid=aid, stage=stage, owner=c.owner)
    return {"written": None, "not_applied": out, "verified": None}


def _waitaof_ms() -> int:
    from ..agent.weights import weights

    return int(weights()["engine"]["waitaof_ms"])


def verify_writeback(c: Ctx, *, aid: str, cause: str, ids: dict) -> dict:
    """Re-read every written id/edge through a SEPARATE read-only connection (RO wrapper, fresh connection)."""
    row = RO(c.tenant, c.graph, fresh=True).run("Q-WB-1", {"inc": c.inc, "cause": cause, "aid": aid,
                                                          "pmid": ids["postmortem"], "did": ids["decision"]}).rows[0]
    checks = {"stage WRITEBACK": row["stage"] == "WRITEBACK", "CAUSED edge": row["caused"] == cause,
              "RESOLVED_BY → APPLIED action": row["verdict"] == "APPLIED", "intent COMMITTED": row["intent_state"] == "COMMITTED",
              "approval recorded": bool(row["approval"]), "postmortem DOCUMENTS incident": bool(row["postmortem"]),
              "decision CITES postmortem": bool(row["decision"])}
    n, m = sum(checks.values()), len(checks)
    return {"verified": f"{n}/{m}", "checks": checks}


__all__ = ["Ctx", "build_options", "propose_data_repair", "choose", "execute", "verify", "write_back", "idem_key", "plan_hash",
           "ensure_infra_repo", "approve", "reject"]


def approve(c: Ctx, aid: str, plan_hash_: str, approver: str, *, via: str = "web",
            tg_user: str | None = None, override: dict | None = None) -> dict | None:
    """Step 2: approve the EXACT action (by its plan hash). None ⇒ stale hash, a different current choice, or not
    awaiting approval (HTTP 409). The same query moves the incident to EXECUTE, so a second approval cannot race.
    `override`: {id, reason} of the active guideline this approval goes past (recorded on the Approval and Action)."""
    prior = [a for a in c.ro().run("Q-ACT-1", {"inc": c.inc}).rows if a["id"] == aid]
    if prior and prior[0]["status"] == "failed":
        return None
    owner = c.ro().run("Q-ACT-INTENT", {"inc": c.inc, "aid": aid}).rows
    if owner and owner[0]["intent_run"] != c.run:  # another run owns this idempotency key: refuse BEFORE any write
        return None
    from .boot import BOOT_ID

    return writes.approve_action(c.g(), inc=c.inc, aid=aid, plan_hash=plan_hash_, approver=approver, run=c.run,
                                 owner=c.owner, lease_ms=lease_ms() if c.owner else 0, boot=BOOT_ID,
                                 world=gh.world_id(), via=via, tg_user=tg_user, override=override)


def reject(c: Ctx, aid: str, plan_hash_: str, approver: str, reason: str) -> dict | None:
    """Reject the EXACT chosen action (by its plan hash), with a reason. None ⇒ stale hash, a different current
    choice, or not awaiting approval (HTTP 409). The option is disabled for good (W-REJECT, one query) and the incident
    stays AWAITING_APPROVAL while another enabled option remains; when none is left, a second conditional query moves
    it to UNKNOWN_ESCALATED with the reason (a human must act). Nothing outside the graph is touched."""
    g = c.g()
    res = writes.reject_action(g, inc=c.inc, aid=aid, plan_hash=plan_hash_, approver=approver, reason=reason, run=c.run)
    if res is not None and writes.escalate_if_no_option_left(
            g, inc=c.inc, run=c.run, why=f"every offered option was rejected or disabled (last: {aid} by {approver}); "
                                          "a human must choose the next step"):
        res["stage"] = "UNKNOWN_ESCALATED"
        res["escalated"] = True
    return res
