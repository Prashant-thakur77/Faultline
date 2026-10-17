"""M19: a scripted on-call night on clean rooms (pre-registered: evals/PREREGISTRATION.md, addendum 2026-10-17).

Drives the real API in-process (TestClient; keyless deterministic investigator; simulated GitHub; in-app pager only):
incident 1 pages the on-call, nobody acks so it escalates along the MSF order, an ack stops it, the on-call approves the
fix (APPLIED) and grants a standing contract, and the same fault again is handled under it with nobody woken; then the
five negative cases (exhausted, revoked, expired, other parameters, the gate abstaining), each one full incident in its
own clean room. The on-call home graph is a fresh GRAPH.COPY of golden_acme; tenant_acme is never written.

    PYTHONPATH=backend uv run python evals/oncall_night.py [--out evals/results/oncall_night.json] [--keep]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TERMINAL = {"RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL", "NO_INCIDENT", "GATE"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "oncall_night.json"))
    ap.add_argument("--keep", action="store_true", help="keep the clean rooms (debugging)")
    ap.add_argument("--reason", default="", help="why this run (a re-run must say why; kept in the results file)")
    a = ap.parse_args()

    from fastapi.testclient import TestClient

    from faultline import api
    from faultline.actions import channels, contracts, oncall
    from faultline.config import settings
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph import writes
    from faultline.graph.ro import RO

    if settings.faultline_public:
        print("refusing: the scripted clock is not allowed on the public demo (FAULTLINE_PUBLIC)")
        return 2
    db = gclient.engine()
    tag = uuid.uuid4().hex[:8]
    home = f"eval_acme_oncallnight_{tag}"
    gcopy.copy_graph(db, "golden_acme", home)
    oncall.home_graph = lambda t: home   # contracts, hand-offs and the report's home: this night's own room
    made: list[str] = [home]
    steps: dict[str, dict] = {}
    t_start = time.time()

    def step(name: str, ok: bool, **kw) -> bool:
        steps[name] = {"pass": bool(ok), **kw}
        print(f"  {'PASS' if ok else 'FAIL'} {name} {json.dumps(kw, default=str)[:300]}")
        return ok

    def run(c, sid="S1"):
        r = c.post(f"/api/scenarios/{sid}/run", json={"llm": "baseline"})
        assert r.status_code == 200, r.text
        r = r.json()
        made.append(r["graph"])
        for _ in range(1200):
            j = c.get(f"/api/jobs/{r['job']}").json()
            if j["state"] != "running":
                break
            time.sleep(0.25)
        return r["incident"], r["graph"], j

    def stage(c, inc):
        return c.get(f"/api/incidents/{inc}").json()["incident"]["stage"]

    def wait(c, inc, timeout=180):
        t0 = time.time()
        st = stage(c, inc)
        while time.time() - t0 < timeout and st not in ("RESOLVED", "FAILED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL"):
            time.sleep(0.3)
            st = stage(c, inc)
        return st

    def pages(c, inc):
        return c.get(f"/api/pages?incident={inc}").json()["rows"]

    def woken(ps):
        return sorted({p["person"]["id"] for p in ps if p["kind"] in ("page", "escalation")})

    def approve_flag(c, inc, who):
        opt = next(o for o in c.get(f"/api/incidents/{inc}/plan").json()["options"]
                   if o["kind"] == "flip_flag" and o["enabled"])
        spec = c.post(f"/api/incidents/{inc}/choose", json={"action_id": opt["id"]}).json()
        r = c.post(f"/api/incidents/{inc}/approve", json={"action_id": opt["id"], "plan_hash": spec["plan_hash"],
                                                          "approver": who})
        return r, opt

    def uses(c):
        return sum(int(x["uses"] or 0) for x in c.get("/api/contracts").json()["rows"])

    out: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "home": home,
                 "channels": [c["channel"] for c in channels.configured() if c["configured"]],
                 "ack_window_min": None, "incidents": {}}
    try:
        with TestClient(api.app) as c:
            api._rate.clear()
            # 1. incident 1 pages the on-call of the failing component's owner team
            inc1, g1, _ = run(c)
            st1 = stage(c, inc1)
            p1 = pages(c, inc1)
            onset = c.get(f"/api/incidents/{inc1}").json()["incident"]["onset_at"]
            rota = {r["team"]: r["person"] for r in RO("acme", g1).run("Q-ONCALL-NOW", {"now": onset}).rows}
            owner = next((p for p in p1 if "failing component" in (p["reason"] or "")), None)
            out["incidents"]["1"] = {"id": inc1, "stage": st1, "pages": len(p1), "woken": woken(p1)}
            out["ack_window_min"] = round((max(p["ack_due_at"] for p in p1) - max(p["sent_at"] for p in p1)) / 60_000, 3) if p1 else None
            step("1_pages_the_on_call", st1 == "AWAITING_APPROVAL" and bool(owner) and owner["status"] == "sent"
                 and owner["kind"] == "page" and owner["person"]["id"] in rota.values()
                 and owner["team"] in rota and rota[owner["team"]] == owner["person"]["id"],
                 stage=st1, pages=len(p1), people=woken(p1), owner=owner and owner["person"]["id"],
                 urgency=owner and owner["urgency"])
            # 2. nobody acks: one escalation at the deadline, none before it
            due = max(p["ack_due_at"] for p in p1)
            before = c.post("/api/oncall/tick", json={"now": due - 1, "incident": inc1}).json()["escalated"]
            esc = c.post("/api/oncall/tick", json={"now": due + 1, "incident": inc1}).json()["escalated"]
            after = pages(c, inc1)
            epage = next((p for p in after if p["kind"] == "escalation"), None)
            nxt = RO("acme", g1).run("Q-PAGE-CHAIN", {"page": epage["id"]}).rows if epage else []
            step("2_no_ack_escalates", not before and len(esc) == 1 and bool(epage)
                 and all(p["status"] == "escalated" and p["escalated_to"] == epage["id"] for p in after if p["kind"] == "page"),
                 escalations=len(esc), to=esc[0]["to"] if esc else None, chain=len(nxt))
            # 3. an ack stops it (forged token refused; the page's own signed token, 60 s after it was sent)
            forged = c.post(f"/api/pages/{epage['id']}/ack", json={"token": "forged"}).status_code if epage else None
            ack = c.post(f"/api/pages/{epage['id']}/ack", json={"token": epage.get("ack_token"),
                                                                "now": epage["sent_at"] + 60_000}) if epage else None
            later = c.post("/api/oncall/tick", json={"now": due + 86_400_000, "incident": inc1}).json()["escalated"]
            acker = (ack.json()["by"]["id"] if ack is not None and ack.status_code == 200 else None)
            step("3_ack_stops_escalation", forged == 403 and ack is not None and ack.status_code == 200 and later == [],
                 forged=forged, ack=ack.status_code if ack is not None else None, by=acker, later=len(later))
            # 4. approve (the VP refused) → APPLIED → grant a contract in two steps
            vp, _ = approve_flag(c, inc1, "p-001")
            ok, opt1 = approve_flag(c, inc1, acker)
            st = wait(c, inc1)
            v1 = next(o for o in c.get(f"/api/incidents/{inc1}/plan").json()["options"] if o["id"] == opt1["id"])
            ch = c.post(f"/api/incidents/{inc1}/contract", json={"step": "choose", "scope": {"max_uses": 1, "days": 7}}).json()
            bad = c.post(f"/api/incidents/{inc1}/contract", json={"step": "approve", "hash": "0" * 64, "approver": acker})
            gr = c.post(f"/api/incidents/{inc1}/contract", json={"step": "approve", "hash": ch.get("hash"), "approver": acker})
            cid = gr.json()["contract"]["id"] if gr.status_code == 200 else None
            step("4_approve_applied_contract", vp.status_code == 403 and ok.status_code == 200 and st == "RESOLVED"
                 and v1["verdict"] == "APPLIED" and bad.status_code == 409 and gr.status_code == 200,
                 vp=vp.status_code, approve=ok.status_code, stage=st, verdict=v1["verdict"], contract=cid,
                 scope=ch.get("scope"), approver_reason=ok.json().get("approver", {}).get("reason"))
            # 5. the same fault again: handled under the contract, nobody woken, verified
            inc2, g2, _ = run(c)
            st2 = wait(c, inc2)
            p2 = pages(c, inc2)
            v2 = next((o for o in c.get(f"/api/incidents/{inc2}/plan").json()["options"] if o.get("verdict")), {})
            ct = next((x for x in c.get("/api/contracts").json()["rows"] if x["id"] == cid), {})
            out["incidents"]["2"] = {"id": inc2, "stage": st2, "pages": len(p2), "woken": woken(p2),
                                     "notices": sum(p["kind"] == "contract_notice" for p in p2), "verdict": v2.get("verdict")}
            step("5_same_fault_under_contract", st2 == "RESOLVED" and not woken(p2)
                 and any(p["kind"] == "contract_notice" for p in p2) and v2.get("verdict") == "APPLIED"
                 and ct.get("uses") == 1 and ct.get("status") == "exhausted"
                 and (ct.get("used_in") or [{}])[0].get("verdict") == "APPLIED",
                 stage=st2, woken=len(woken(p2)), notices=out["incidents"]["2"]["notices"], verdict=v2.get("verdict"),
                 uses=ct.get("uses"), status=ct.get("status"))

            # negatives: each a full incident; the contract must not fire, humans are paged
            neg: dict[str, dict] = {}

            def negative(name: str, sid: str = "S1") -> dict:
                u0 = uses(c)
                inc, g, _ = run(c, sid)
                st = wait(c, inc)
                ps = pages(c, inc)
                fired = uses(c) != u0 or any(p["kind"] == "contract_notice" for p in ps)
                neg[name] = {"incident": inc, "graph": g, "stage": st, "woken": woken(ps), "fired": fired}
                expect_stage = "AWAITING_APPROVAL" if sid == "S1" else st
                step(f"neg_{name}", not fired and bool(woken(ps)) and st == expect_stage, stage=st, woken=len(woken(ps)),
                     fired=fired)
                return neg[name]

            na = negative("a_exhausted")
            okA, _ = approve_flag(c, na["incident"], na["woken"][0] if na["woken"] else acker)
            stA = wait(c, na["incident"])
            # (b) revoked: granted from (a)'s verified fix, then revoked
            chb = c.post(f"/api/incidents/{na['incident']}/contract",
                         json={"step": "choose", "scope": {"max_uses": 3, "days": 7}}).json()
            grb = c.post(f"/api/incidents/{na['incident']}/contract",
                         json={"step": "approve", "hash": chb.get("hash"), "approver": acker})
            cid_b = grb.json()["contract"]["id"] if grb.status_code == 200 else None
            rv = c.post(f"/api/contracts/{cid_b}/revoke", json={"by": acker}).status_code if cid_b else None
            steps["neg_b_setup"] = {"pass": okA.status_code == 200 and stA == "RESOLVED" and grb.status_code == 200 and rv == 200,
                                    "approve": okA.status_code, "stage": stA, "grant": grb.status_code, "revoke": rv}
            negative("b_revoked")
            # (c) expired: the same offer/grant path with the clock 8 days back, 7 days
            past = oncall.now_ms() - 8 * 86_400_000
            old = contracts.offer(tenant="acme", graph=na["graph"], inc=na["incident"], home=home, max_uses=3, days=7, now=past)
            gc_ = contracts.grant(tenant="acme", home=home, hash_=old["hash"], by=acker, now=past)
            now_view = contracts.one("acme", home, old["contract_id"]) or {}   # its status at the real clock
            steps["neg_c_setup"] = {"pass": bool(gc_) and now_view.get("status") == "expired",
                                    "contract": old["contract_id"], "status": now_view.get("status"),
                                    "expires_at": now_view.get("expires_at")}
            negative("c_expired")
            # (d) other parameters: an active contract for the same family and action kind, another flag
            g = gclient.engine().select_graph(home)
            now = oncall.now_ms()
            fam = (ch.get("scope") or {}).get("family")
            prm = {**((ch.get("scope") or {}).get("params") or {}), "flag": "anotherFlagEntirely"}
            ph = contracts.params_hash("flip_flag", prm)
            writes.offer_contract(g, cid="ct-" + "d" * 16, tenant="acme", family=fam, kind="flip_flag", params_hash=ph,
                                  params=prm, max_uses=3, days=7, expires_at=now + 7 * 86_400_000, now=now, ttl_ms=600_000,
                                  hash_="d" * 64, inc=na["incident"], graph=na["graph"], aid="", covers=fam, quote="other flag")
            gd = writes.grant_contract(g, cid="ct-" + "d" * 16, hash_="d" * 64, by=acker, covers=fam, now=now)
            steps["neg_d_setup"] = {"pass": bool(gd), "family": fam, "params_hash": ph}
            negative("d_other_params")
            # (e) the gate abstains: S12, with an active contract for its inferred component and the same action kind
            prm_e = (ch.get("scope") or {}).get("params") or {}
            ph_e = contracts.params_hash("flip_flag", prm_e)
            writes.offer_contract(g, cid="ct-" + "e" * 16, tenant="acme", family="currency", kind="flip_flag",
                                  params_hash=ph_e, params=prm_e, max_uses=3, days=7, expires_at=now + 7 * 86_400_000,
                                  now=now, ttl_ms=600_000, hash_="e" * 64, inc="", graph="", aid="", covers="currency",
                                  quote="inferred component")
            ge = writes.grant_contract(g, cid="ct-" + "e" * 16, hash_="e" * 64, by=acker, covers="currency", now=now)
            steps["neg_e_setup"] = {"pass": bool(ge)}
            ne = negative("e_gate_abstains", "S12")
            job_outcome = next((r for r in c.get("/api/incidents").json() if r["incident"] == ne["incident"]), {}).get("outcome")
            steps["neg_e_gate_abstains"]["outcome"] = job_outcome
            steps["neg_e_gate_abstains"]["pass"] = steps["neg_e_gate_abstains"]["pass"] and job_outcome in (
                "NOT_CONFIDENT", "UNKNOWN_ESCALATED")

            # read back from the night's OWN graphs (its home and the clean rooms it made), with the same templates the
            # API uses (Q-ONCALL-STATS, Q-SHIFT-REPORT): the API reads every graph of the tenant, including runs that are
            # not part of this night (PREREGISTRATION amendment 3). The report window reaches past the scripted clock.
            ours = list(dict.fromkeys(made))
            st_ = oncall.stats("acme", since=int(t_start * 1000) - 1000, graphs=ours)
            rep = oncall.report("acme", since=int(t_start * 1000) - 1000, until=oncall.now_ms() + 2 * 86_400_000,
                                graphs=ours)
            out["stats"] = {k: st_.get(k) for k in ("pages", "incidents", "people_paged", "mtta_ms", "mttr_ms",
                                                     "handled_under_contract", "acked_incidents", "resolved_incidents")}
            out["report"] = {"counts": rep["counts"], "summary": rep["summary"]}
            out["negatives"] = neg
            # MTTA from the graph (Q-ONCALL-STATS) against the same mean computed here from the pages the API returns:
            # per incident with an acknowledged page, its first acknowledgement minus its first page (incident 1's is
            # the scripted ack; an approval also acknowledges, case (a))
            delays = []
            for inc in [inc1, inc2] + [v["incident"] for v in neg.values()]:
                ps = [p for p in pages(c, inc) if p["kind"] in ("page", "escalation")]
                acks = [p["ack"]["at"] for p in ps if p.get("ack")]
                if ps and acks:
                    delays.append(min(acks) - min(p["sent_at"] for p in ps))
            out["ack_delays_ms"] = delays
            out["mtta_expected_ms"] = round(sum(delays) / len(delays)) if delays else None
            out["scripted_ack_ms"] = (epage["sent_at"] + 60_000 - min(p["sent_at"] for p in p1)) if epage and p1 else None
    finally:
        if not a.keep:
            for gname in made:
                gcopy.delete_if_exists(db, gname)
    passed = [k for k, v in steps.items() if v["pass"]]
    out.update(steps=steps, passed=len(passed), total=len(steps), seconds=round(time.time() - t_start, 1),
               negatives_fired=sum(1 for v in out.get("negatives", {}).values() if v["fired"]),
               negatives=len(out.get("negatives", {})), reason=a.reason)
    prev_path = Path(a.out)
    if prev_path.exists():  # every earlier run stays on record (a re-run never hides the one before it)
        prev = json.loads(prev_path.read_text())
        out["earlier_runs"] = list(prev.get("earlier_runs") or []) + [{
            "started": prev.get("started"), "passed": prev.get("passed"), "total": prev.get("total"),
            "negatives_fired": prev.get("negatives_fired"), "reason": prev.get("reason", ""),
            "failed": sorted(k for k, v in (prev.get("steps") or {}).items() if not v.get("pass"))}]
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"oncall night: {len(passed)}/{len(steps)} steps pass; negatives fired {out['negatives_fired']}/{out['negatives']}; "
          f"{out['seconds']} s → {a.out}")
    return 0 if len(passed) == len(steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
