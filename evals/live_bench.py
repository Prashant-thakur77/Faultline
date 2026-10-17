"""Live benchmark: measure the public deployment the way a visitor or a judge meets it, over HTTPS.

What it measures (all against the deployed URL, nothing local):
  * availability: /api/status answers with the pinned engine, the template count and the release;
  * page loads: time to first byte and full HTML for each top-level page (repeated, p50/p95);
  * API latency: /api/status round trips (p50/p95);
  * the hero incident end to end, several times: time to a verdict (AWAITING_APPROVAL), whether the confirmed cause
    and outcome match the scenario's truth file (read here, by the grader only), then choose + approve on the run's
    token and time to RESOLVED, with the recorded verification verdict;
  * the data incident (S2) to its verdict;
  * company brain answers and a preflight verdict (latency, and the preflight decision for a PR that must block);
  * the hosted MCP endpoint refuses a request without a key.
It re-arms the demo at the end so the site is left clean. Writes evals/results/live_bench.json; evals/report.py folds
it into latest.json as live.* keys, so README numbers stay checked by `make claims`.

    uv run python evals/live_bench.py [--base https://13-203-185-119.sslip.io] [--runs 5]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals" / "results" / "live_bench.json"
TENANT = "acme"
PAGES = ["/", "/preflight", "/brain", "/memory", "/explore", "/replay", "/replay/s1-hero"]
PAYMENT_BEFORE = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}, "currency": "USD"}, separators=(",", ":"))
PREFLIGHT_BLOCK = {  # the S6 example from the UI: a timeout raise that drops retries; the gate must block it
    "repo": "Prashant-thakur77/faultline-demo-app", "number": 7, "author": "p-017", "head_sha": "5e6a1c0",
    "title": "payment: raise client timeout to 5000 ms, drop retries",
    "files": [{"path": "src/payment/config.json", "before": PAYMENT_BEFORE,
               "after": json.dumps({"client": {"timeout_ms": 5000, "retries": 0}, "currency": "USD"}, separators=(",", ":"))}],
}
QUESTIONS = ["Who owns checkout?", "Who decided the payment timeout?", "What does the payment service depend on?"]


def http(base: str, method: str, path: str, body: dict | None = None, headers: dict | None = None,
         timeout: float = 60.0) -> tuple[int, dict | list, float]:
    """One request; returns (status, json body or {}, milliseconds)."""
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "user-agent": "faultline-live-bench",
                                          **(headers or {})})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ms = (time.perf_counter() - t0) * 1000
            try:
                return r.status, json.loads(raw or b"{}"), ms
            except json.JSONDecodeError:
                return r.status, {}, ms
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode(errors="replace")[:300]}, (time.perf_counter() - t0) * 1000


def page(base: str, path: str) -> tuple[int, float, float, int]:
    """(status, ms to first byte, ms to full body, bytes) for one page load."""
    req = urllib.request.Request(base + path, headers={"user-agent": "faultline-live-bench"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read(1)
        ttfb = (time.perf_counter() - t0) * 1000
        n = 1 + len(r.read())
        return r.status, ttfb, (time.perf_counter() - t0) * 1000, n


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 1) if xs else 0.0


def stage(base: str, inc: str) -> str:
    _, d, _ = http(base, "GET", f"/api/incidents/{inc}?tenant={TENANT}")
    return ((d or {}).get("incident") or {}).get("stage", "") if isinstance(d, dict) else ""


def wait(base: str, inc: str, stages: set[str], timeout: float = 300.0) -> tuple[str, float]:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        st = stage(base, inc)
        if st in stages:
            return st, (time.perf_counter() - t0) * 1000
        time.sleep(0.25)
    raise RuntimeError(f"{inc} did not reach {sorted(stages)} within {timeout:.0f} s (last {stage(base, inc)!r})")


def listed(base: str, inc: str, timeout: float = 30.0) -> dict:
    """The incident's row in the run index. The index (audit graph) records the outcome a moment after the incident's
    own graph reaches its stage, so wait until it leaves RUNNING: reading it earlier graded a confirmed run as wrong."""
    t0, row = time.perf_counter(), {}
    while time.perf_counter() - t0 < timeout:
        _, rows, _ = http(base, "GET", f"/api/incidents?tenant={TENANT}")
        row = next((r for r in rows if r.get("incident") == inc), {}) if isinstance(rows, list) else {}
        if row.get("outcome") not in (None, "RUNNING"):
            return row
        time.sleep(0.25)
    return row


def start(base: str, sid: str) -> tuple[str, dict]:
    """POST a run; a data scenario answers with its job first (the warehouse rebuilds in its fixture mode before
    intake opens the incident), so poll /api/jobs/<job> until the incident exists. Returns (incident, token header)."""
    code, r, _ = http(base, "POST", f"/api/scenarios/{sid}/run", {"llm": "baseline"})
    if code != 200:
        raise RuntimeError(f"{sid} run refused: HTTP {code} {r}")
    hdr = {"x-faultline-run-token": r["run_token"]} if r.get("run_token") else {}
    t0 = time.perf_counter()
    while not r.get("incident") and time.perf_counter() - t0 < 600:
        time.sleep(0.5)
        _, j, _ = http(base, "GET", f"/api/jobs/{r['job']}?tenant={TENANT}", headers=hdr)
        incs = j.get("incidents") or []
        r["incident"] = j.get("incident") or (incs[0].get("incident") if incs and isinstance(incs[0], dict) else
                                              incs[0] if incs else None)
        if j.get("state") in ("failed", "error"):
            raise RuntimeError(f"{sid} job failed: {j}")
    if not r.get("incident"):
        raise RuntimeError(f"{sid} job opened no incident in time")
    return r["incident"], hdr


def hero_run(base: str, truth: dict) -> dict:
    t0 = time.perf_counter()
    inc, hdr = start(base, "S1")
    st, _ = wait(base, inc, {"AWAITING_APPROVAL", "FAILED", "NO_INCIDENT"})
    verdict_ms = (time.perf_counter() - t0) * 1000
    row = listed(base, inc)
    out = {"incident": inc, "stage_at_verdict": st, "verdict_ms": round(verdict_ms, 1), "outcome": row.get("outcome"),
           "cause": row.get("cause"), "cause_correct": row.get("cause") == truth["cause"] and row.get("outcome") == truth["outcome"]}
    plan = http(base, "GET", f"/api/incidents/{inc}/plan?tenant={TENANT}")[1]
    opt = next(o for o in plan["options"] if o["enabled"] and o["kind"] in ("flip_flag", "rollback_deploy"))
    t1 = time.perf_counter()
    c, spec, _ = http(base, "POST", f"/api/incidents/{inc}/choose?tenant={TENANT}", {"action_id": opt["id"]}, hdr)
    c2, _, _ = http(base, "POST", f"/api/incidents/{inc}/approve?tenant={TENANT}",
                    {"action_id": opt["id"], "plan_hash": spec["plan_hash"], "approver": "p-030"}, hdr)
    final, _ = wait(base, inc, {"RESOLVED", "UNKNOWN_ESCALATED", "FAILED"})
    detail = json.dumps(http(base, "GET", f"/api/incidents/{inc}?tenant={TENANT}")[1])
    out.update({"choose": c, "approve": c2, "final": final, "act_ms": round((time.perf_counter() - t1) * 1000, 1),
                "total_ms": round((time.perf_counter() - t0) * 1000, 1), "applied": '"APPLIED"' in detail,
                "action": opt["kind"]})
    return out


def run(base: str, runs: int) -> dict:
    t_start = time.perf_counter()
    res: dict = {"base": base, "runs": runs, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    code, s, _ = http(base, "GET", f"/api/status?tenant={TENANT}")
    res["status"] = {"http": code, "engine": (s.get("engine") or {}).get("engine"), "templates": s.get("templates"),
                     "version": s.get("version"), "acl": s.get("acl"), "llm_configured": s.get("llm_configured")}

    lat = [http(base, "GET", f"/api/status?tenant={TENANT}")[2] for _ in range(20)]
    res["api_status_ms"] = {"n": len(lat), "p50": pct(lat, 0.5), "p95": pct(lat, 0.95)}

    pages: dict = {}
    for p in PAGES:
        rows = [page(base, p) for _ in range(5)]
        pages[p] = {"ok": all(r[0] == 200 for r in rows), "ttfb_p50": pct([r[1] for r in rows], 0.5),
                    "load_p50": pct([r[2] for r in rows], 0.5), "kb": round(rows[-1][3] / 1024, 1)}
    res["pages"] = pages
    res["pages_ok"] = sum(1 for v in pages.values() if v["ok"])
    res["pages_ttfb_p50"] = pct([v["ttfb_p50"] for v in pages.values()], 0.5)
    res["pages_load_max_p50"] = max(v["load_p50"] for v in pages.values())

    truth = json.loads((ROOT / "data" / "scenarios" / "S1.truth.json").read_text())
    hero = [hero_run(base, truth) for _ in range(runs)]
    res["hero"] = {"runs": hero, "n": len(hero), "cause_correct": sum(h["cause_correct"] for h in hero),
                   "resolved": sum(h["final"] == "RESOLVED" for h in hero), "applied": sum(h["applied"] for h in hero),
                   "verdict_ms_p50": pct([h["verdict_ms"] for h in hero], 0.5),
                   "verdict_ms_max": round(max(h["verdict_ms"] for h in hero), 1),
                   "act_ms_p50": pct([h["act_ms"] for h in hero], 0.5),
                   "total_ms_p50": pct([h["total_ms"] for h in hero], 0.5)}

    truth2 = json.loads((ROOT / "data" / "scenarios" / "S2.truth.json").read_text())
    t0 = time.perf_counter()
    inc2, _ = start(base, "S2")
    st, _ = wait(base, inc2, {"AWAITING_APPROVAL", "FAILED", "NO_INCIDENT", "RESOLVED"}, 600)
    row = listed(base, inc2)
    res["s2"] = {"stage": st, "verdict_ms": round((time.perf_counter() - t0) * 1000, 1), "cause": row.get("cause"),
                 "cause_correct": row.get("cause") == truth2.get("cause") and row.get("outcome") == truth2.get("outcome")}

    brain = [http(base, "POST", "/api/brain/ask", {"question": q, "tenant": TENANT}, timeout=90) for q in QUESTIONS]
    res["brain"] = {"n": len(brain), "ok": sum(b[0] == 200 and bool((b[1] or {}).get("answer")) for b in brain),
                    "ms_p50": pct([b[2] for b in brain], 0.5)}

    code, pf, ms = http(base, "POST", f"/api/preflight?tenant={TENANT}", PREFLIGHT_BLOCK, timeout=90)
    res["preflight"] = {"http": code, "decision": (pf or {}).get("verdict") if isinstance(pf, dict) else None, "ms": round(ms, 1)}

    code, _, _ = http(base, "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    res["mcp_unauthenticated_http"] = code

    time.sleep(61)  # the re-arm limit is one per minute per visitor
    code, ra, _ = http(base, "POST", f"/api/demo/rearm?tenant={TENANT}", timeout=120)
    res["rearm"] = {"http": code, "status": (ra or {}).get("status") if isinstance(ra, dict) else None}
    res["seconds"] = round(time.perf_counter() - t_start, 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://13-203-185-119.sslip.io")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()
    res = run(a.base.rstrip("/"), a.runs)
    OUT.write_text(json.dumps(res, indent=2) + "\n")
    h = res["hero"]
    print(json.dumps({k: res[k] for k in ("status", "api_status_ms", "pages_ok", "pages_ttfb_p50", "s2", "brain",
                                          "preflight", "mcp_unauthenticated_http", "rearm", "seconds")}, indent=1))
    print(f"hero: {h['cause_correct']}/{h['n']} right cause, {h['resolved']}/{h['n']} resolved, {h['applied']}/{h['n']} "
          f"APPLIED; verdict p50 {h['verdict_ms_p50']} ms, end to end p50 {h['total_ms_p50']} ms")
    ok = (res["status"]["http"] == 200 and res["pages_ok"] == len(PAGES) and h["cause_correct"] == h["n"]
          and h["applied"] == h["n"] and res["mcp_unauthenticated_http"] == 401)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
