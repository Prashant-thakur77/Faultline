"""Company-brain held-out eval: questions written blind (data/brain/heldout_blind.truth.json, heldout_blind2.truth.json).

A separate agent wrote these questions from the README's claims and the synthetic org's data. It never saw the
router, its intents or its templates. Expected ids were derived from read-only queries. The router is never tuned on
this file; it is scored once per router version and the result is reported as it is.

Per question, scoring is content-based, because the held-out "kind" names are the author's, not the router's:
- answerable: every expected id is cited and the citation guard passed;
- unanswerable (expect_ids == []): no citations at all.

The questions are asked in a fresh clean room (a GRAPH.COPY of golden_<t>, deleted afterwards), like brain_eval.

    PYTHONPATH=backend .venv/bin/python evals/brain_heldout.py [--label NAME] [--side]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.brain.ask import ask  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.tenant import golden_graph  # noqa: E402

SETS = {"1": "heldout_blind.truth.json", "2": "heldout_blind2.truth.json"}
SIDE = ROOT / "evals" / "results" / "brain_heldout.json"


def run(set_id: str = "1") -> dict:
    truth = json.loads((ROOT / "data" / "brain" / SETS[set_id]).read_text())
    tenant = truth["tenant"]
    db = gclient.engine()
    room = f"eval_{tenant}_brainheld_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, golden_graph(tenant), room)
    rows = []
    try:
        for q in truth["questions"]:
            t0 = time.perf_counter()
            a = ask(q["question"], tenant, graph=room)
            cited = set(a.citations)
            want = set(q["expect_ids"])
            ok = (want <= cited and bool(a.guard.get("ok"))) if want else not cited
            rows.append({"id": q["id"], "kind": q["kind"], "ok": ok, "intent": a.intent,
                         "missing": sorted(want - cited), "cited": sorted(cited),
                         "ms": round((time.perf_counter() - t0) * 1000, 1)})
    finally:
        db.select_graph(room).delete()
    k = sum(r["ok"] for r in rows)
    by_kind: dict[str, list[int]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], [0, 0])
        by_kind[r["kind"]][0] += r["ok"]
        by_kind[r["kind"]][1] += 1
    return {"correct": k, "questions": len(rows), "by_kind": by_kind, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="current", help="the router version scored (e.g. keyword, graph-intents)")
    ap.add_argument("--side", action="store_true", help=f"record the result in {SIDE.relative_to(ROOT)}")
    ap.add_argument("--reason", default="", help="why this run (logged in the side file)")
    ap.add_argument("--set", default="1", choices=sorted(SETS), help="which blind set (each written by a separate agent)")
    a = ap.parse_args()
    out = run(a.set)
    print(f"held-out brain set {a.set} [{a.label}]: {out['correct']}/{out['questions']}")
    for kind, (k, n) in sorted(out["by_kind"].items()):
        print(f"  {kind:20s} {k}/{n}")
    if a.side:
        prev = json.loads(SIDE.read_text()) if SIDE.exists() else {"runs": []}
        prev["runs"].append({"set": a.set, "label": a.label, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason, **out})
        SIDE.write_text(json.dumps(prev, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
