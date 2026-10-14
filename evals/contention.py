"""Contention on the real action path (M17, W3.3): many responders act on the same incident at the same moment.

1. **Same plan.** S1 runs to AWAITING_APPROVAL through the API (keyless, simulated GitHub persisted to a file). One
   option is chosen, then N responders POST the SAME approval (action id + plan hash) at once (a barrier releases every
   thread together). The approval query moves the incident to EXECUTE in the same atomic write that approves the plan,
   so exactly one request can be accepted and the rest are refused at approval.
2. **Different plans.** A fresh S1 run; responders race to choose and approve DIFFERENT enabled options at once. The
   plan hash binds each approval to the option that was chosen; still exactly one approval may land.

Measured from the product's own records (RO templates, never raw Cypher): HTTP outcomes, approvals in the graph,
intents (MERGEd on the idempotency key), PRs in the simulated GitHub for the approved change, Operator crew steps,
and the final stage. Nothing here is a lost-update counter: there is nothing to increment on this path.

    PYTHONPATH=backend uv run python evals/contention.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

from chaos import TENANT, Api, _http, _prs, _wait_stage  # noqa: E402

RESPONDERS = 24


def _post_from(base: str, path: str, body: dict, headers: dict, source: str) -> int:
    """POST from a given loopback address: each responder is its own client, as 24 people on 24 machines would be
    (the API's per-client rate limits stay in force; on Linux all of 127.0.0.0/8 is loopback)."""
    import http.client
    from urllib.parse import urlparse

    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30, source_address=(source, 0))
    try:
        c.request("POST", path, body=json.dumps(body), headers={"content-type": "application/json", **headers})
        return c.getresponse().status
    finally:
        c.close()
SETTLED = {"RESOLVED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL", "FAILED"}


def _race(n: int, fire) -> list[int]:
    """Run `fire(i)` from n threads released together; returns the HTTP codes in thread order."""
    gate = threading.Barrier(n)
    codes: list[int] = [0] * n

    def go(i: int) -> None:
        gate.wait()
        codes[i] = fire(i)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return codes


def _to_approval(base: str, timeout_s: float) -> tuple[dict, dict, dict]:
    code, r = _http(base, "POST", "/api/scenarios/S1/run", {"llm": "baseline"})
    if code != 200:
        raise RuntimeError(f"run S1: HTTP {code} {r}")
    _wait_stage(base, r["incident"], {"AWAITING_APPROVAL"}, timeout_s)
    plan = _http(base, "GET", f"/api/incidents/{r['incident']}/plan?tenant={TENANT}")[1]
    hdr = {"x-faultline-run-token": r["run_token"]} if r.get("run_token") else {}
    return r, plan, hdr


def _record(r: dict, ro, world: dict, branches: list[str]) -> dict:
    row = ro.run("Q-CONTEND-1", {"inc": r["incident"], "run": r["run"]}).rows[0]
    return {**row, "prs": sum(len(_prs(world, b)) for b in branches)}


def run(n: int = RESPONDERS, timeout_s: float = 180.0) -> dict:
    from faultline.graph.ro import RO

    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="faultline-contention-"))
    state = work / "github"
    state.mkdir()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "FAULTLINE_SIM_GITHUB_DIR": str(state),
           "FAULTLINE_GITHUB": "sim", "FAULTLINE_PUBLIC": "false", "FAULTLINE_CREATE_PR": "false"}
    out: dict = {"responders": n}
    api = Api(env, work / "api.log")
    try:
        api.wait_up()
        # 1. the same approval, n times at once
        r, plan, hdr = _to_approval(api.base, timeout_s)
        opt = next(o for o in plan["options"] if o["enabled"] and o["kind"] in ("flip_flag", "rollback_deploy"))
        code, spec = _http(api.base, "POST", f"/api/incidents/{r['incident']}/choose?tenant={TENANT}", {"action_id": opt["id"]}, hdr)
        if code != 200:
            raise RuntimeError(f"choose: HTTP {code} {spec}")
        body = {"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"}
        codes = _race(n, lambda i: _post_from(api.base, f"/api/incidents/{r['incident']}/approve?tenant={TENANT}", body, hdr,
                                              f"127.0.1.{i + 1}"))
        stage = _wait_stage(api.base, r["incident"], SETTLED, timeout_s)
        world = json.loads((state / f"{r['graph']}.json").read_text())
        same = {"http": dict(Counter(codes)), "accepted": codes.count(200), "refused": n - codes.count(200),
                "final_stage": stage, **_record(r, RO(TENANT, r["graph"]), world, [spec["branch"]])}
        same["ok"] = (same["accepted"] == 1 and same["approved_actions"] == 1 and same["intents"] == 1
                      and same["prs"] == 1 and same["operator_steps"] == 1)
        out["same_plan"] = same

        # 2. different plans: responders choose and approve different enabled options at once
        r2, plan2, hdr2 = _to_approval(api.base, timeout_s)
        opts = [o for o in plan2["options"] if o["enabled"]]
        specs: dict[str, dict] = {}
        for o in opts:   # each responder holds the plan hash of the option it chose (choose is idempotent per option)
            c, sp = _http(api.base, "POST", f"/api/incidents/{r2['incident']}/choose?tenant={TENANT}", {"action_id": o["id"]}, hdr2)
            if c == 200:
                specs[o["id"]] = sp
        ids = sorted(specs)
        if len(ids) < 2:
            out["different_plans"] = {"skipped": f"only {len(ids)} option(s) could be chosen"}
        else:
            def fire(i: int) -> int:
                aid = ids[i % len(ids)]
                return _post_from(api.base, f"/api/incidents/{r2['incident']}/approve?tenant={TENANT}",
                                  {"action_id": aid, "plan_hash": specs[aid]["plan_hash"], "approver": "p-030"}, hdr2,
                                  f"127.0.2.{i + 1}")

            codes2 = _race(n, fire)
            won = sorted({ids[i % len(ids)] for i, c in enumerate(codes2) if c == 200})
            kinds = {o["id"]: o["kind"] for o in opts}
            stage2 = _wait_stage(api.base, r2["incident"], SETTLED, timeout_s)
            world2 = json.loads((state / f"{r2['graph']}.json").read_text())
            diff = {"options": len(ids), "winner_kind": [kinds[w] for w in won], "http": dict(Counter(codes2)),
                    "accepted": codes2.count(200),
                    "refused": n - codes2.count(200), "final_stage": stage2,
                    **_record(r2, RO(TENANT, r2["graph"]), world2, [s["branch"] for s in specs.values() if s.get("branch")])}
            diff["ok"] = diff["accepted"] == 1 and diff["approved_actions"] == 1 and diff["intents"] <= 1 and diff["operator_steps"] == 1
            out["different_plans"] = diff
    finally:
        api.stop()
    out["ok"] = bool(out["same_plan"]["ok"] and out.get("different_plans", {}).get("ok", False))
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


if __name__ == "__main__":
    res = run()
    p = ROOT / "evals" / "results" / "contention.json"
    p.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
    sys.exit(0 if res["ok"] else 1)
