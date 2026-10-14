"""The FalkorDB capability ladder (PREREGISTRATION amendment 2026-10-13).

On the 100 held-out gate-bench worlds (seed 20261015), one capability is removed at a time and everything else runs as
shipped:
  full           the product
  no_maxflow     algo.maxFlow off: G5 slack 0, every suspect with a path passes sufficiency (the A3-noG5 switch)
  no_sppaths     algo.SPpaths replaced by mere connectivity: a suspect passes G2 when its component and the symptom
                 are in one weakly connected component of the failure edges (algo.WCC), with no direction
  neither        both removed
Graded with the bench's own expected verdicts. Reported per rung: correct, wrong-confident, abstained.

    PYTHONPATH=backend uv run python evals/ladder.py [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402
import mismatch_eval  # noqa: E402
from faultline.agent.weights import weights  # noqa: E402

SEED = 20261015
RUNGS = {"full": {}, "no_maxflow": {"flow_slack": 0.0}, "no_sppaths": {"ablate_g2_connectivity": True},
         "neither": {"flow_slack": 0.0, "ablate_g2_connectivity": True}}


@contextmanager
def _switched(changes: dict):
    g = weights()["gate"]
    saved = {k: g.get(k, None) for k in changes}
    g.update(changes)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                g.pop(k, None)
            else:
                g[k] = v


def run(seed: int = SEED, progress: bool = True) -> dict:
    t0 = time.perf_counter()
    cases = gate_bench.generate(seed=seed)
    out: dict = {"seed": seed, "cases": len(cases), "rungs": {}}
    for name, changes in RUNGS.items():
        with _switched(changes):
            rows = [mismatch_eval.run_case(c, None) for c in cases]
        s = mismatch_eval.summarise(rows) | {"buckets": gate_bench.buckets(rows, cases)}
        s["wrong"] = [{k: r[k] for k in ("id", "category", "outcome", "blamed")} for r in rows if r["wrong_confident"]]
        out["rungs"][name] = s
        if progress:
            print(f"[ladder] {name}: correct {s['correct']}, wrong-confident {s['wrong_confident']}, "
                  f"abstained {s['abstained']}", file=sys.stderr, flush=True)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run()
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
