"""The T2 (Agent Memory & Coordination) go/no-go checklist of run and recorded with its evidence.

  1. cold vs warm measured on ≥ 2 scenarios with N ≥ 3      ← evals/results/learning_night.json (M21, pre-registered)
  2. S13 concurrency passes                                  ← evals/concurrency.py (16 workers × 100 rounds), re-run now
  3. S7 isolation passes                                     ← tests/isolation, and again through the shipped ro_<t> ACL users
  4. S10 supersession/forget receipt works on the live URL   ← the live URL's read-only forget dry run; the full forget locally
  5. Session/Turn history persists across sessions, read back ← two sessions of one user on a clean room, read back with
                                                                Q-SESS-1 on a separate read-only connection

Each item is green or red with its evidence; a red item is reported, never loosened.

    PYTHONPATH=backend uv run python evals/t2_gonogo.py [--live-url https://…] [--out evals/results/t2_gonogo.json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
LIVE_URL = "https://13-203-185-119.sslip.io"


def _junit(args: list[str], env: dict | None = None) -> dict:
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "j.xml"
        r = subprocess.run(args + [f"--junitxml={xml}", "-q", "-p", "no:warnings"], cwd=ROOT, capture_output=True,
                           text=True, env={**os.environ, "PYTHONPATH": "backend", **(env or {})}, timeout=1800)
        if not xml.exists():
            return {"ok": False, "error": (r.stdout + r.stderr)[-400:]}
        root = ET.parse(xml).getroot()
        s = root if root.tag == "testsuite" else root.find("testsuite")
        t, sk = int(s.get("tests", 0)), int(s.get("skipped", 0))
        bad = int(s.get("failures", 0)) + int(s.get("errors", 0))
        return {"ok": r.returncode == 0, "passed": t - bad - sk, "failed": bad, "skipped": sk}


def _http(method: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "faultline-t2-gonogo"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"status": r.status, "json": json.loads(r.read().decode() or "null"), "ms": round((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:300], "ms": round((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001 - unreachable from here (sandbox, network): recorded as such
        return {"status": None, "error": f"{type(e).__name__}: {e}"[:300], "ms": round((time.time() - t0) * 1000)}


def cold_vs_warm() -> dict:
    p = ROOT / "evals" / "results" / "learning_night.json"
    if not p.exists():
        return {"green": False, "why": "evals/results/learning_night.json missing: run evals/learning_night.py"}
    x = json.loads(p.read_text())
    st, ch = x["steps"], x["phases"].get("choices") or {}
    pairs = (x["phases"].get("recall") or {}).get("pairs") or []
    scen = sorted({c["scenario"] for c in ch.get("cold", [])})
    n_min = min([sum(1 for c in ch.get("cold", []) if c["scenario"] == s) for s in scen] or [0])
    green = (len(scen) >= 2 and n_min >= 3 and all(st[k]["pass"] for k in ("1_cold_top_rollback", "1_warm_top_flag",
                                                                         "1_gate_verdicts_identical_cold_warm"))
             and len(pairs) >= 6 and st.get("5_recall_warm_top_is_recent_and_gate_unchanged", {}).get("pass", False))
    return {"green": green, "scenarios": scen, "n_per_scenario": n_min,
            "choices": {"cold_top": [c["top"] for c in ch.get("cold", [])], "warm_top": [c["top"] for c in ch.get("warm", [])]},
            "recall_pairs": sorted({p_["pair"] for p_ in pairs}), "recall_trials": len(pairs),
            "evidence": "evals/results/learning_night.json (steps 1_* and 5_*)", "run": x.get("started")}


def s13() -> dict:
    out = ROOT / "evals" / "results" / "t2_concurrency.json"   # its own file: concurrency.json is the M2 record
    r = subprocess.run([sys.executable, "evals/concurrency.py", "--workers", "16", "--rounds", "100", "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "backend"}, timeout=1800)
    if not out.exists():
        return {"green": False, "why": (r.stdout + r.stderr)[-400:]}
    x = json.loads(out.read_text())
    green = x["rounds_with_exactly_one_owner"] == x["rounds"] and x["lost_updates"] == 0 and r.returncode == 0
    return {"green": green, "workers": x["workers"], "rounds": x["rounds"],
            "rounds_with_exactly_one_owner": x["rounds_with_exactly_one_owner"], "lost_updates": x["lost_updates"],
            "ro_p95_ms_during_writes": x["ro_read_ms"]["during_writes"]["p95"], "evidence": "evals/results/t2_concurrency.json"}


def s7() -> dict:
    plain = _junit([sys.executable, "-m", "pytest", "tests/isolation"])
    acl = subprocess.run([sys.executable, "scripts/acl_ephemeral.py", "tests/isolation", "-q", "-p", "no:warnings"], cwd=ROOT,
                         capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "backend"}, timeout=1800)
    tail = (acl.stdout + acl.stderr).strip().splitlines()[-1:] or [""]
    return {"green": plain["ok"] and acl.returncode == 0, "isolation_suite": plain,
            "through_ro_acl_users": {"ok": acl.returncode == 0, "summary": tail[0][-200:]},
            "evidence": "pytest tests/isolation; scripts/acl_ephemeral.py tests/isolation"}


def s10(live_url: str) -> dict:
    local = _junit([sys.executable, "-m", "pytest", "tests/memory", "tests/live/test_forget_flip.py",
                    "tests/live/test_learning_live.py::test_reject_guideline_override_then_forget_with_a_receipt"])
    ln = json.loads((ROOT / "evals" / "results" / "learning_night.json").read_text()) if \
        (ROOT / "evals" / "results" / "learning_night.json").exists() else {}
    learned = (ln.get("steps") or {}).get("forget_reverts_and_receipts", {})
    status = _http("GET", f"{live_url}/api/status")
    dry = _http("POST", f"{live_url}/api/memory/forget?tenant=acme", {"doc_id": "doc-adr-021"})
    learned_live = _http("GET", f"{live_url}/api/learned?tenant=acme")
    dj = dry.get("json") or {}
    live_ok = dry.get("status") == 200 and bool(dj.get("dry_run")) and len(str(dj.get("token") or "")) == 64
    return {"green": bool(local["ok"] and learned.get("pass") and live_ok),
            "local": {"forget_receipt_suites": local, "learned_influence_forget": learned},
            "live_url": {"url": live_url, "status": status.get("status"), "status_error": status.get("error"),
                         "forget_dry_run": {"status": dry.get("status"), "dry_run": dj.get("dry_run"),
                                            "token": bool(dj.get("token")), "nodes": dj.get("nodes"),
                                            "vectors": dj.get("vectors"), "error": dry.get("error")},
                         "learned_endpoint_status": learned_live.get("status"),
                         "note": "read-only on the live URL: the forget dry run (no token) deletes nothing; an executed "
                                 "forget there writes a receipt to the live audit graph, so it is run locally"},
            "evidence": "tests/memory, tests/live/test_forget_flip.py, learning_night forget step, the live dry run"}


def session() -> dict:
    from faultline.brain.ask import ask
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy
    from faultline.graph.ro import RO

    db = gclient.engine()
    room = f"eval_acme_t2sess_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "tenant_acme", room)
    user = f"t2-{uuid.uuid4().hex[:6]}"
    try:
        a1 = ask("Who owns payment?", "acme", user=user, session="t2-morning", graph=room)
        a2 = ask("And who knows it best?", "acme", user=user, session="t2-evening", graph=room)
        rows = RO("acme", room, fresh=True).run("Q-SESS-1", {"user": user}).rows   # a separate read-only connection
        sessions = sorted({r["session"] for r in rows})
        follow = a2.answer
    finally:
        gcopy.delete_if_exists(db, room)
    green = sessions == ["sess-t2-evening", "sess-t2-morning"] and len(rows) == 4 and "[" in follow
    return {"green": green, "sessions": sessions, "turns": len(rows), "first_answer_cites": a1.citations[:3],
            "follow_up_resolved_from_history": "[" in follow, "follow_up": follow[:160],
            "evidence": "brain.ask twice (two sessions, one user) on a clean room, read back with Q-SESS-1 (fresh RO)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "t2_gonogo.json"))
    ap.add_argument("--live-url", default=LIVE_URL)
    a = ap.parse_args()
    t0 = time.time()
    items = {}
    for name, fn in (("cold_vs_warm", cold_vs_warm), ("s13_concurrency", s13), ("s7_isolation", s7),
                     ("s10_forget_receipt", lambda: s10(a.live_url.rstrip("/"))), ("session_turns", session)):
        try:
            items[name] = fn()
        except Exception as e:  # noqa: BLE001 - a crashed check is red, with its reason
            items[name] = {"green": False, "why": f"{type(e).__name__}: {e}"[:400]}
        print(f"  {'GREEN' if items[name]['green'] else 'RED  '} {name} {json.dumps(items[name], default=str)[:220]}")
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": items,
           "green": sum(1 for v in items.values() if v["green"]), "total": len(items), "seconds": round(time.time() - t0, 1)}
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"T2 go/no-go: {out['green']}/{out['total']} green → {a.out}")
    return 0 if out["green"] == out["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
