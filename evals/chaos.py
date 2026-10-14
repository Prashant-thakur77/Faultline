"""SIGKILL chaos check (M12 wave-2 item 7, M13 item 11): kill the API with `kill -9` between EXECUTE and VERIFY (or,
with pause=after_merge_before_record, between the GitHub merge and the graph's record of it) and show that the intent
is settled exactly once.

1. Start the API as a subprocess (keyless, simulated GitHub persisted to a file so the outside world survives the
   kill, FAULTLINE_CHAOS_PAUSE=after_execute so the action job stops right after the external change was made and
   recorded, before verification).
2. Run S1 through the API to AWAITING_APPROVAL, choose the first enabled production-changing option, approve its plan
   hash. Wait for the pause marker, then SIGKILL the process.
3. Restart the API (no pause) and do nothing else: the killed process's intent lease names its boot, whose
   heartbeat goes stale `actions.boot_stale_s` after the kill, and the restarted API's periodic reconciler
   (`actions.reconcile_every_s`, first pass once a predecessor's heartbeat is stale) takes the lease over and settles
   it. Real clock throughout (review round 5, M1): no `now` is moved, nothing is called by hand.
4. Check: one PR for the idempotency key, verified APPLIED, write-back verified n/n, stage RESOLVED, settled by the
   restarted API's reconciler; a second reconcile (this process) finds nothing; a re-execute of the same approval is
   refused.
5. Control (naive retry): on a copy of the post-crash world, re-execute the approved change WITHOUT the idempotency
   key (a fresh branch per attempt, no lookup), as a retry-on-restart would. That opens and merges a second PR: the
   double action the intent/idempotency design prevents.

No raw Cypher: reads go through the RO templates; writes only through the product (API, act, reconcile).

    PYTHONPATH=backend uv run python evals/chaos.py
"""

from __future__ import annotations

import copy
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

TENANT = "acme"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(base: str, method: str, path: str, body: dict | None = None, headers: dict | None = None,
          timeout: float = 30.0) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode()[:400]}


class Api:
    def __init__(self, env: dict, log: Path):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = open(log, "ab")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "faultline.api:app", "--port", str(self.port),
                                      "--app-dir", "backend", "--log-level", "warning"], cwd=ROOT, env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)

    def wait_up(self, timeout: float = 120.0) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"API exited with {self.proc.returncode} (log: {self.log.name})")
            try:
                if _http(self.base, "GET", "/api/status", timeout=5)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"API did not come up in {timeout}s (log: {self.log.name})")

    def sigkill(self) -> int:
        os.kill(self.proc.pid, signal.SIGKILL)
        return self.proc.wait(timeout=30)

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


def _stage(base: str, inc: str) -> str:
    code, view = _http(base, "GET", f"/api/incidents/{inc}?tenant={TENANT}")
    return view["incident"]["stage"] if code == 200 else f"HTTP {code}"


def _wait_stage(base: str, inc: str, stages: set[str], timeout: float = 180.0) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = _stage(base, inc)
        if st in stages:
            return st
        time.sleep(0.3)
    raise RuntimeError(f"{inc} did not reach {sorted(stages)} (last: {_stage(base, inc)})")


def _prs(world: dict, branch: str) -> list[dict]:
    return [p for p in world.get("prs", {}).values() if p["head"] == branch]


def naive_retry(hub, spec: dict, attempt: int) -> dict:
    """What a retry WITHOUT the idempotency key does after a crash: the same approved change, a fresh branch, no lookup
    of an earlier PR, no check of main. (Control only; the product never does this.)"""
    from faultline.actions import github as gh

    repo = spec["args"]["repo"]
    branch = f"{gh.FIX_PREFIX}retry-{attempt}-{int(time.time() * 1000)}"
    hub.create_branch(repo, branch)
    hub.put_file(repo, branch, spec["file"], spec["after"], spec["commit"])
    pr = hub.open_pr(repo, branch, spec["commit"].splitlines()[0], spec["pr_body"])
    hub.merge_pr(repo, pr["number"])
    return pr


KILL_POINTS = {
    "after_execute": "after_execute: the PR is opened, merged and recorded; verification has not run",
    "after_merge_before_record": "after_merge_before_record: the PR is merged at GitHub; the graph has no record of it yet",
}


def run(timeout_s: float = 180.0, pause: str = "after_execute") -> dict:
    """`pause`: where the API is killed (KILL_POINTS); the reconciler must settle the intent exactly once either way."""
    from faultline import api
    from faultline.actions import act, reconcile
    from faultline.actions import github as gh
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO

    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="faultline-chaos-"))
    state, marker, log = work / "github", work / "paused", work / "api.log"
    state.mkdir()
    base_env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "FAULTLINE_SIM_GITHUB_DIR": str(state),
                "FAULTLINE_GITHUB": "sim", "FAULTLINE_PUBLIC": "false", "FAULTLINE_CREATE_PR": "false"}
    out: dict = {"kill_point": KILL_POINTS[pause]}
    graph = inc = None
    a1 = Api({**base_env, "FAULTLINE_CHAOS_PAUSE": pause, "FAULTLINE_CHAOS_MARKER": str(marker)}, log)
    try:
        a1.wait_up()
        code, r = _http(a1.base, "POST", "/api/scenarios/S1/run", {"llm": "baseline"})
        if code != 200:
            raise RuntimeError(f"run S1: HTTP {code} {r}")
        inc, graph, token = r["incident"], r["graph"], r.get("run_token", "")
        hdr = {"x-faultline-run-token": token} if token else {}
        _wait_stage(a1.base, inc, {"AWAITING_APPROVAL"}, timeout_s)
        plan = _http(a1.base, "GET", f"/api/incidents/{inc}/plan?tenant={TENANT}")[1]
        opt = next(o for o in plan["options"] if o["enabled"] and o["kind"] in ("flip_flag", "rollback_deploy"))
        code, spec = _http(a1.base, "POST", f"/api/incidents/{inc}/choose?tenant={TENANT}", {"action_id": opt["id"]}, hdr)
        if code != 200:
            raise RuntimeError(f"choose: HTTP {code} {spec}")
        approver = ((plan.get("who_fixes") or {}).get("payload") or {}).get("rows", [{}])[0].get("person", "p-030")
        code, ap = _http(a1.base, "POST", f"/api/incidents/{inc}/approve?tenant={TENANT}",
                         {"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": approver}, hdr)
        if code != 200:
            raise RuntimeError(f"approve: HTTP {code} {ap}")
        t_wait = time.time()
        while not marker.exists():
            if time.time() - t_wait > timeout_s:
                raise RuntimeError("the action job never reached the pause point")
            time.sleep(0.2)
        out["option"] = {"kind": opt["kind"], "target": opt["target"]}
        out["killed_exit"] = a1.sigkill()
    finally:
        a1.stop()
    try:
        world_file = state / f"{graph}.json"
        world = json.loads(world_file.read_text())
        branch = spec["branch"]
        c = act.Ctx(TENANT, graph, inc, r["run"])
        it = RO(TENANT, graph).run("Q-ACT-INTENT", {"inc": inc, "aid": opt["id"]}).rows[0]
        out["after_kill"] = {"stage": it["stage"], "intent": it["intent_state"], "prs": len(_prs(world, branch)),
                             "merged": [p["state"] for p in _prs(world, branch)]}
        out["recorded_before_kill"] = it["status"] == "executed"   # False in the merge-before-record window
        control_world = copy.deepcopy(world)
        # 3. restart and wait: the restarted API settles the intent by itself once the killed boot's heartbeat is stale
        from faultline.agent.weights import weights

        w = weights()["actions"]
        settle_s = float(w["boot_stale_s"]) + 2 * float(w["boot_heartbeat_s"]) + float(w["reconcile_every_s"]) + 60.0
        a2 = Api(base_env, log)
        try:
            a2.wait_up()
            out["restart_ok"] = True
            t_up = time.time()
            out["after_restart"] = {"stage": _stage(a2.base, inc),
                                    "intent": RO(TENANT, graph).run("Q-ACT-INTENT", {"inc": inc, "aid": opt["id"]}).rows[0][
                                        "intent_state"]}
            final_stage = _wait_stage(a2.base, inc, {"RESOLVED", "UNKNOWN_ESCALATED", "AWAITING_APPROVAL", "FAILED"},
                                      settle_s)
            out["settled_by_restarted_api_s"] = round(time.time() - t_up, 1)
            notes = [st.get("note") or "" for st in _http(a2.base, "GET", f"/api/incidents/{inc}?tenant={TENANT}")[1]["stages"]]
        finally:
            a2.stop()  # a clean stop: its boot is ended
        rec_note = next((n for n in reversed(notes) if n.startswith("reconciled (")), "")
        found = rec_note[len("reconciled ("):rec_note.find(")")] if rec_note else None
        wb = rec_note.rsplit("write-back verified ", 1)[-1].split()[0] if "write-back verified " in rec_note else None
        row = next(a for a in RO(TENANT, graph).run("Q-ACT-1", {"inc": inc}).rows if a["id"] == opt["id"])
        out["reconciled"] = [{"found": found, "verdict": row["verdict"], "writeback": wb}] if rec_note else []
        out["final_stage_seen"] = final_stage
        # 4. a second reconcile in this process (real clock) finds nothing left for this incident
        os.environ["FAULTLINE_SIM_GITHUB_DIR"] = str(state)
        gh.reset_sim(graph)
        hub = gh.client(graph)

        def world_of(i: str) -> dict | None:
            cc, loc = api._actx(i, TENANT)
            return api._world(cc, loc)

        again = reconcile.reconcile(TENANT, graph, hub, world_of)
        out["second_reconcile_settled"] = len([x for x in again if x["incident"] == inc])
        try:
            act.execute(c, opt["id"], hub)
            out["re_execute_refused"] = False
        except PermissionError as e:
            out["re_execute_refused"] = True
            out["re_execute_reason"] = str(e)[:160]
        world = json.loads(world_file.read_text())
        row = next(a for a in RO(TENANT, graph).run("Q-ACT-1", {"inc": inc}).rows if a["id"] == opt["id"])
        it = RO(TENANT, graph).run("Q-ACT-INTENT", {"inc": inc, "aid": opt["id"]}).rows[0]
        out["final"] = {"stage": it["stage"], "intent": it["intent_state"], "verdict": row["verdict"],
                        "prs": len(_prs(world, branch)), "prs_merged": sum(p["state"] == "merged" for p in _prs(world, branch)),
                        "writeback": (out["reconciled"] or [{}])[0].get("writeback")}
        # 5. control: naive retry without the idempotency key, on a copy of the post-crash world
        ctl = gh.SimGitHub(files=control_world["files"], prs={int(k): v for k, v in control_world["prs"].items()},
                           issues={int(k): v for k, v in control_world["issues"].items()})
        before = len(ctl.prs)
        naive_retry(ctl, spec, 1)
        merged = [p for p in ctl.prs.values() if p["state"] == "merged"]
        out["control_naive_retry"] = {"prs_before": before, "prs_after": len(ctl.prs), "merged_prs": len(merged),
                                      "same_change_merged_twice": len(merged) >= 2}
        wb = out["final"]["writeback"] or "0/1"
        n, m = (int(x) for x in wb.split("/"))
        out["exactly_once"] = (out["final"]["prs"] == 1 and out["final"]["prs_merged"] == 1
                               and out["final"]["intent"] == "COMMITTED" and out["final"]["verdict"] == "APPLIED"
                               and n == m and out["final"]["stage"] == "RESOLVED" and out["second_reconcile_settled"] == 0
                               and out["re_execute_refused"])
        out["double_action_in_control"] = out["control_naive_retry"]["same_change_merged_twice"]
        out["ok"] = bool(out["exactly_once"] and out["double_action_in_control"] and out["after_kill"]["intent"] == "PENDING")
    finally:
        os.environ.pop("FAULTLINE_SIM_GITHUB_DIR", None)
        gh.reset_sim(graph)
        if graph:
            gcopy.delete_if_exists(gclient.engine(), graph)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    if out.get("ok"):
        import shutil

        shutil.rmtree(work, ignore_errors=True)  # our own mkdtemp scratch; kept (with the API log) on failure
    else:
        out["log"] = str(log)
    return out


if __name__ == "__main__":
    res = run(pause=sys.argv[1] if len(sys.argv) > 1 else "after_execute")
    print(json.dumps(res, indent=2))
    raise SystemExit(0 if res.get("ok") else 1)
