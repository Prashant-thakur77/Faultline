"""M21: learning from recent work and from the people using it (pre-registered: evals/PREREGISTRATION.md, addendum
2026-10-17, "M21 learning").

Drives the real API in-process (TestClient; keyless deterministic investigator; simulated GitHub; in-app pager only;
off the public demo, so every run is trusted). Learned state lives in a fresh GRAPH.COPY of golden_acme per phase (the
on-call home graph is patched to it); tenant_acme and oncall_acme are never written. Phases: 1 choices (cold vs warm,
S1 and S1b, N = 3) with 4 the contract suggestion, 2 guidelines, 3 who responds (paging order, MTTA before/after),
forget (with a receipt), 6 knowledge gaps, 5 recency-aware recall (harness._cold_vs_warm, S1→S1b and S3→S3b, N = 3).

    PYTHONPATH=backend uv run python evals/learning_night.py [--out evals/results/learning_night.json] [--keep]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

STOP = ("RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL", "NO_INCIDENT")
ONCALL = "p-030"     # on call for team-payments, which owns payment (the family of S1 and S1b)
MEMBER = "p-017"     # a team-payments member, not on call: the responder who answers in phase 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "learning_night.json"))
    ap.add_argument("--keep", action="store_true", help="keep the graphs (debugging)")
    ap.add_argument("--reason", default="", help="why this run (a re-run must say why; kept in the results file)")
    ap.add_argument("--skip-recall", action="store_true", help="skip phase 5 (development only; never for the record)")
    a = ap.parse_args()
    logging.disable(logging.INFO)

    from fastapi.testclient import TestClient

    from faultline import api
    from faultline.actions import oncall
    from faultline.config import settings
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO
    from faultline.memory import learning

    if settings.faultline_public:
        print("refusing: the scripted clock is not allowed on the public demo (FAULTLINE_PUBLIC)")
        return 2
    db = gclient.engine()
    tag = uuid.uuid4().hex[:8]
    made: list[str] = []
    current = [""]

    def new_home(name: str) -> str:
        g = f"eval_acme_learn_{name}_{tag}"
        gcopy.copy_graph(db, "golden_acme", g)
        made.append(g)
        current[0] = g
        return g

    oncall.home_graph = lambda t: current[0]   # learning, contracts and hand-offs live in this phase's own home
    steps: dict[str, dict] = {}
    out: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "reason": a.reason,
                 "weights": {k: v for k, v in learning.w().items()}, "phases": {}}
    t_start = time.time()

    def step(name: str, ok: bool, **kw) -> bool:
        steps[name] = {"pass": bool(ok), **kw}
        print(f"  {'PASS' if ok else 'FAIL'} {name} {json.dumps(kw, default=str)[:260]}")
        return ok

    def run(c, sid: str) -> tuple[str, str]:
        r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"})
        assert r.status_code == 200, r.text
        r = r.json()
        made.append(r["graph"])
        for _ in range(1200):
            j = c.get(f"/api/jobs/{r['job']}").json()
            if j["state"] != "running":
                break
            time.sleep(0.25)
        return r["incident"], r["graph"]

    def stage(c, inc: str) -> str:
        return c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]

    def wait(c, inc: str, timeout: float = 180) -> str:
        t0, st = time.time(), stage(c, inc)
        while time.time() - t0 < timeout and st not in STOP:
            time.sleep(0.3)
            st = stage(c, inc)
        return st

    def plan(c, inc: str) -> dict:
        return c.get(f"/api/incidents/{inc}/plan").json()

    def verdict(c, inc: str) -> tuple:
        rep = c.get(f"/api/incidents/{inc}").json()
        cause = (rep.get("report") or {}).get("cause") or next((g["cause"] for g in reversed(rep.get("gate_runs") or [])
                                                                if g.get("passed")), None)
        return rep["incident"].get("confident"), cause

    def flag(p: dict) -> dict:
        return next(o for o in p["options"] if o["kind"] == "flip_flag" and o["enabled"])

    def choose(c, inc: str, opt: dict) -> dict:
        return c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()

    def approve(c, inc: str, opt: dict, who: str, **extra):
        spec = choose(c, inc, opt)
        return c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                              "approver": who, **extra})

    def pages(c, inc: str) -> list[dict]:
        return c.get(f"/api/pages?incident={inc}").json()["rows"]

    try:
        with TestClient(api.app) as c:
            api._rate.clear()
            # ---------------------------------------------------------------- 1 + 4: choices, cold vs warm, suggestion
            new_home("cold")
            cold: list[dict] = []
            for sid in ("S1", "S1b"):
                for _ in range(3):
                    inc, _g = run(c, sid)
                    p = plan(c, inc)
                    cold.append({"scenario": sid, "incident": inc, "top": p["options"][0]["kind"], "verdict": verdict(c, inc),
                                 "learned": p["learned"].get("n_family")})
            step("1_cold_top_rollback", all(x["top"] == "rollback_deploy" for x in cold),
                 tops=[x["top"] for x in cold])
            home1 = new_home("h1")
            learning_plans: list[dict] = []
            for k, sid in enumerate(("S1", "S1b", "S1", "S1b", "S1"), 1):
                inc, _g = run(c, sid)
                p = plan(c, inc)
                f = flag(p)
                sug = (f.get("learned") or {}).get("contract_suggestion")
                r = approve(c, inc, f, ONCALL)
                st = wait(c, inc)
                learning_plans.append({"plan": k, "scenario": sid, "incident": inc, "top": p["options"][0]["kind"],
                                       "suggested": bool(sug), "suggest_n": (sug or {}).get("n"),
                                       "approve": r.status_code, "stage": st, "learned": r.json().get("learned")})
            flips = [x["plan"] for x in learning_plans if x["top"] == "flip_flag"]
            pref_min = int(learning.w()["pref_min_n"])
            step("1_learning_flips_after_min_n", bool(flips) and flips[0] == pref_min + 1
                 and all(x["top"] == "flip_flag" for x in learning_plans if x["plan"] > pref_min)
                 and all(x["approve"] == 200 and x["stage"] == "RESOLVED" for x in learning_plans),
                 tops=[x["top"] for x in learning_plans], stages=[x["stage"] for x in learning_plans])
            k_sug = int(learning.w()["contract_suggest_k"])
            step("4_suggestion_after_k_never_before", all(x["suggested"] == (x["plan"] > k_sug) for x in learning_plans),
                 suggested=[x["suggested"] for x in learning_plans], n=[x["suggest_n"] for x in learning_plans])
            warm: list[dict] = []
            for sid in ("S1", "S1b"):
                for _ in range(3):
                    inc, _g = run(c, sid)
                    p = plan(c, inc)
                    top = p["options"][0]
                    warm.append({"scenario": sid, "incident": inc, "top": top["kind"], "verdict": verdict(c, inc),
                                 "line": ((top.get("learned") or {}).get("preference") or {}).get("line"),
                                 "moved": p["learned"].get("moved")})
            step("1_warm_top_flag", all(x["top"] == "flip_flag" and "5 of the last 5" in (x["line"] or "") for x in warm),
                 tops=[x["top"] for x in warm], line=warm[0]["line"] if warm else None)
            same = all(x["verdict"] == y["verdict"] for x, y in zip(sorted(cold, key=lambda r: r["scenario"]),
                                                                       sorted(warm, key=lambda r: r["scenario"])))
            step("1_gate_verdicts_identical_cold_warm", same and all(x["verdict"][1] for x in cold + warm),
                 cold=[x["verdict"] for x in cold][:2], warm=[x["verdict"] for x in warm][:2])
            out["phases"]["choices"] = {"cold": cold, "learning": learning_plans, "warm": warm}

            # ---------------------------------------------------------------- 2: rejections → guidelines
            inc, _g = run(c, "S1")
            f = flag(plan(c, inc))
            spec = choose(c, inc, f)
            reason = "flag off hides the revenue KPI from the dashboard; roll the deploy back instead"
            rj = c.post(f"/api/incidents/{inc}/reject", json={"action_id": f["id"], "plan_hash": spec["plan_hash"],
                                                              "approver": ONCALL, "reason": reason})
            gl = [g for g in c.get("/api/learned").json()["guidelines"]["rows"] if g["action_kind"] == "flip_flag"]
            gid = gl[0]["id"] if gl else None
            step("2a_rejection_proposes_a_guideline", rj.status_code == 200 and len(gl) == 1 and gl[0]["status"] == "proposed"
                 and gl[0]["text"] == reason and gl[0]["by"]["id"] == ONCALL and gl[0]["incident"] == inc,
                 reject=rj.status_code, guideline=gid, status=gl[0]["status"] if gl else None)
            inc2, _g = run(c, "S1")
            g2 = (flag(plan(c, inc2)).get("learned") or {}).get("guideline") or {}
            pr = c.post(f"/api/learned/guidelines/{gid}", json={"action": "promote", "by": MEMBER})
            step("2b_shown_with_provenance_then_promoted", g2.get("id") == gid and g2.get("status") == "proposed"
                 and g2.get("by") == ONCALL and g2.get("incident") == inc and bool(g2.get("event"))
                 and not g2.get("needs_override") and pr.status_code == 200 and pr.json()["guideline"]["status"] == "active",
                 shown=g2.get("status"), event=g2.get("event"), promote=pr.status_code)
            inc3, _g = run(c, "S1")
            p3 = plan(c, inc3)
            f3 = flag(p3)
            g3 = (f3.get("learned") or {}).get("guideline") or {}
            no_ovr = approve(c, inc3, f3, ONCALL)
            with_ovr = approve(c, inc3, f3, ONCALL, override_guideline=gid,
                               override_reason="checkout is down; the KPI gap is acceptable for an hour")
            st3 = wait(c, inc3)
            ovr_events = [e for e in c.get("/api/learned").json()["events"]["rows"] if e["kind"] == "override"]
            step("2c_active_guideline_needs_override", g3.get("needs_override") is True and p3["options"][0]["kind"] != "flip_flag"
                 and no_ovr.status_code == 409 and gid in no_ovr.text and with_ovr.status_code == 200
                 and st3 == "RESOLVED" and len(ovr_events) == 1,
                 top=p3["options"][0]["kind"], without=no_ovr.status_code, with_override=with_ovr.status_code, stage=st3,
                 override_events=len(ovr_events))
            dm = c.post(f"/api/learned/guidelines/{gid}", json={"action": "dismiss", "by": MEMBER})
            inc4, _g = run(c, "S1")
            g4 = (flag(plan(c, inc4)).get("learned") or {}).get("guideline")
            step("2d_dismissed_is_gone", dm.status_code == 200 and g4 is None, dismiss=dm.status_code, shown=g4)
            out["phases"]["guidelines"] = {"guideline": gid, "incidents": [inc, inc2, inc3, inc4]}

            # ---------------------------------------------------------------- forget p-030 (H1)
            dry = c.post("/api/learned/forget", json={"person": ONCALL}).json()
            stale = c.post("/api/learned/forget", json={"person": ONCALL, "token": "0" * 64, "approver": MEMBER})
            ex = c.post("/api/learned/forget", json={"person": ONCALL, "token": dry["token"], "approver": MEMBER})
            exj = ex.json() if ex.status_code == 200 else {}
            receipt = next((r for r in RO("acme", "audit_acme").run("Q-LEARN-RECEIPTS", {}).rows
                            if r["token"] == dry["token"]), None)
            incf, _g = run(c, "S1")
            pf = plan(c, incf)
            st_after = c.get("/api/learned").json()
            step("forget_reverts_and_receipts", ex.status_code == 200 and stale.status_code == 409
                 and exj.get("events_left") == 0 and exj.get("preferences_still_citing") == 0
                 and exj.get("events") == dry["n_events"] and pf["options"][0]["kind"] == "rollback_deploy"
                 and receipt is not None and receipt["events_left"] == 0 and receipt["approver"] == MEMBER
                 and not ((pf["options"][0].get("learned") or {}).get("preference"))
                 and not st_after["preferences"]["rows"] and not [g for g in st_after["guidelines"]["rows"]
                                                                   if g["by"]["id"] == ONCALL],
                 events=dry["n_events"], by_kind=dry["by_kind"], stale=stale.status_code, execute=ex.status_code,
                 left=exj.get("events_left"), top_after=pf["options"][0]["kind"])
            out["phases"]["forget"] = {"dry_run": {k: dry[k] for k in ("n_events", "by_kind", "families", "guidelines")},
                                       "receipt": {k: exj.get(k) for k in ("events", "guidelines", "relationships",
                                                                            "events_left", "preferences_still_citing",
                                                                            "proof")}}
            out["phases"]["forget"]["receipt_in_audit"] = bool(receipt)
            _ = home1

            # ---------------------------------------------------------------- 3: who responds → paging order, MTTA
            new_home("h2")
            routing: list[dict] = []
            for k in range(1, 6):
                inc, g = run(c, "S1")
                ps = pages(c, inc)
                first_at = min(p["sent_at"] for p in ps if p["kind"] in ("page", "escalation"))
                wave1 = sorted({p["person"]["id"] for p in ps if p["kind"] == "page" and p["attempt"] == 1})
                learned_first = [p["person"]["id"] for p in ps if (p["reason"] or "").startswith("learned responder")]
                acked_at, ticks = None, 0
                for _ in range(9):
                    ps = pages(c, inc)
                    mine = [p for p in ps if p["person"]["id"] == MEMBER and p["status"] in ("sent", "delivery_failed")
                            and p["kind"] in ("page", "escalation")]
                    if mine:
                        r = c.post(f"/api/pages/{mine[0]['id']}/ack", json={"token": mine[0]["ack_token"],
                                                                            "now": mine[0]["sent_at"] + 60_000})
                        if r.status_code == 200:
                            acked_at = mine[0]["sent_at"] + 60_000
                        break
                    if ticks >= 8:
                        break
                    open_ = [p for p in ps if p["status"] in ("sent", "delivery_failed") and p["kind"] in ("page", "escalation")]
                    if not open_:
                        break
                    c.post("/api/oncall/tick", json={"now": max(p["ack_due_at"] for p in open_) + 1, "incident": inc})
                    ticks += 1
                routing.append({"incident": inc, "first_wave": wave1, "learned_first": learned_first,
                                "oncall_paged": ONCALL in wave1, "ticks": ticks,
                                "mtta_ms": (acked_at - first_at) if acked_at else None,
                                "plan_first_wave": plan(c, inc)["learned"].get("first_wave")})
            rmin = int(learning.w()["resp_min_n"])
            before = [x for i, x in enumerate(routing, 1) if i <= rmin]
            after = [x for i, x in enumerate(routing, 1) if i > rmin]
            mtta_b = [x["mtta_ms"] for x in before if x["mtta_ms"] is not None]
            mtta_a = [x["mtta_ms"] for x in after if x["mtta_ms"] is not None]
            step("3_responder_paged_first_after_learning",
                 all(MEMBER not in x["first_wave"] for x in before) and all(x["learned_first"] == [MEMBER] for x in after)
                 and all(x["plan_first_wave"] == [MEMBER] for x in after) and all(x["oncall_paged"] for x in routing)
                 and len(mtta_b) == len(before) and len(mtta_a) == len(after)
                 and all(m >= 5 * 60_000 for m in mtta_b) and all(m == 60_000 for m in mtta_a),
                 waves=[x["first_wave"] for x in routing], mtta=[x["mtta_ms"] for x in routing])
            out["phases"]["routing"] = {"incidents": routing,
                                        "mtta_before_ms": round(sum(mtta_b) / len(mtta_b)) if mtta_b else None,
                                        "mtta_after_ms": round(sum(mtta_a) / len(mtta_a)) if mtta_a else None}
            resp = [r for r in c.get("/api/learned").json()["responders"]["rows"] if r["person"]["id"] == MEMBER]
            out["phases"]["routing"]["responder"] = resp[0] if resp else None

            # ---------------------------------------------------------------- 6: knowledge gaps
            from faultline.brain.ask import ask

            new_home("h3")
            room = f"eval_acme_learn_brain_{tag}"
            gcopy.copy_graph(db, "tenant_acme", room)
            made.append(room)
            qs = [("What did we decide about the quantum billing ledger?", "gap"),
                  ("What did we decide about the quantum billing ledger?", "gap"),
                  ("Who owns the hyperdrive service?", "gap"), ("Who owns payment?", "answered"),
                  ("What is the weather in Paris tomorrow?", "off-topic")]
            asked = []
            for q, kind in qs:
                ans = ask(q, "acme", graph=room).as_dict()
                rec = learning.on_gap("acme", ans, "eval-user", trusted_=True)
                asked.append({"question": q, "kind": kind, "intent": ans["intent"], "gap": bool(rec)})
            gaps = c.get("/api/learned").json()["gaps"]["rows"]
            step("6_gaps_counted", sorted(int(x["n"]) for x in gaps) == [1, 2] and all(x["status"] == "open" for x in gaps)
                 and [a_["gap"] for a_ in asked] == [True, True, True, False, False],
                 gaps=[(x["text"][:40], x["n"]) for x in gaps], asked=[a_["gap"] for a_ in asked])
            out["phases"]["gaps"] = {"asked": asked, "gaps": [{k: x.get(k) for k in ("text", "n", "reason", "owners")}
                                                              for x in gaps]}

            # ---------------------------------------------------------------- 5: recency-aware recall
            if not a.skip_recall:
                import harness

                pairs = []
                for first, repeat in (("S1", "S1b"), ("S3", "S3b")):
                    for _ in range(3):
                        cw = harness._cold_vs_warm(first, repeat)
                        w = cw["warm"]
                        pairs.append({"pair": cw["pair"], "warm_top_is_first": bool(w.get("top_precedent_is_s1",
                                                                                         w.get("top_precedent_is_first"))),
                                      "gate_identical": cw["gate_verdicts_identical"],
                                      "cold_prior": cw["cold"].get("prior_payment", cw["cold"].get("prior")),
                                      "warm_prior": w.get("prior_payment", w.get("prior"))})
                step("5_recall_warm_top_is_recent_and_gate_unchanged",
                     all(x["warm_top_is_first"] for x in pairs) and all(x["gate_identical"] for x in pairs),
                     pairs=[(x["pair"], x["warm_top_is_first"], x["gate_identical"]) for x in pairs])
                out["phases"]["recall"] = {"pairs": pairs, "ages": _recency_ages(db, gcopy, made, tag)}
    finally:
        if not a.keep:
            for gname in made:
                gcopy.delete_if_exists(db, gname)
    passed = [k for k, v in steps.items() if v["pass"]]
    out.update(steps=steps, passed=len(passed), total=len(steps), seconds=round(time.time() - t_start, 1))
    prev_path = Path(a.out)
    if prev_path.exists():  # every earlier run stays on record
        prev = json.loads(prev_path.read_text())
        out["earlier_runs"] = list(prev.get("earlier_runs") or []) + [{
            "started": prev.get("started"), "passed": prev.get("passed"), "total": prev.get("total"),
            "reason": prev.get("reason", ""), "failed": sorted(k for k, v in (prev.get("steps") or {}).items()
                                                               if not v.get("pass"))}]
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"learning night: {len(passed)}/{len(steps)} steps pass; {out['seconds']} s → {a.out}")
    return 0 if len(passed) == len(steps) else 1


def _recency_ages(db, gcopy, made: list[str], tag: str) -> dict:
    """Informational (pre-registered): on cold rooms, Q-MEM-1's top precedent and its age with w_recency 0 (similarity
    only, the order before M21) and the configured weight."""
    from faultline import scenario
    from faultline.agent.weights import weights
    from faultline.graph.ro import RO

    m = weights()["memory"]
    hl = float(m["half_life_days"]) * 86_400_000
    out = {}
    for sid in ("S1", "S1b", "S3", "S14"):
        p = scenario.prepare(sid, set_mode=False)
        made.append(p.graph)
        try:
            row = {}
            for wr in (0.0, float(m["recall_recency_w"])):
                rows = RO(p.tenant, p.graph).run("Q-MEM-1", {"current": p.incident_id, "now": p.onset_ms,
                                                             "half_life_ms": hl, "w_recency": wr}).rows
                row[str(wr)] = {"top": rows[0]["id"] if rows else None,
                                "age_days": round(float(rows[0]["age_ms"]) / 86_400_000, 1) if rows else None,
                                "set": [r["id"] for r in rows]}
            row["top_changed"] = row["0.0"]["top"] != row[str(float(m["recall_recency_w"]))]["top"]
            out[sid] = row
        finally:
            gcopy.delete_if_exists(db, p.graph)
    _ = tag
    return out


if __name__ == "__main__":
    raise SystemExit(main())
