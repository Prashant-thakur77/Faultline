"""The scenario suite with real trial variance (PREREGISTRATION amendment 2026-10-16).

The deterministic investigator makes `make eval`'s 3 trials per scenario identical copies. Here each trial is a
different WORLD: the telemetry simulator's seed (base rates and per-minute noise) changes; injected changes, effects and
alerts do not. Seeds: 42 (the canonical one) + 1001–1004 (K = 5). S2 and S4D are data scenarios with no simulated
telemetry, so they run at the canonical seed only (more seeds would be identical copies).
Arms: N, V, T, T+, A3, A3-noG5 (evals/harness.py), graded by the harness grader against the scenario truth files.
Writes evals/results/scenario_seeds.json (keys seeds.scen.* in latest.json).

    PYTHONPATH=backend scripts/memguard.sh 4000 uv run python evals/scenario_seeds.py --reason "…"
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import harness  # noqa: E402
from faultline import scenario  # noqa: E402

SEEDS = (42, 1001, 1002, 1003, 1004)
DATA_SCENARIOS = ("S2", "S4D")   # no simulated telemetry: the seed changes nothing
OUT = ROOT / "evals" / "results" / "scenario_seeds.json"


def _arm(name: str, sid: str, spec: dict) -> dict:
    if name == "N":
        return harness.arm_naive(sid)
    if name == "V":
        return harness.arm_vector(sid, spec)
    if name == "T":
        return harness.arm_telemetry(sid, spec)
    if name == "T+":
        return harness.arm_telemetry(sid, spec, plus=True)
    if name == "A3":
        return harness._graph_arm(sid, nomem=False, spec=spec)
    if name == "A3-noG5":
        return harness._graph_arm(sid, nomem=False, no_g5=True, spec=spec)
    raise ValueError(name)


ARMS = ("N", "V", "T", "T+", "A3", "A3-noG5")


def strict_fields(sid: str, t: dict) -> dict:
    """Tie-aware grading (amendment 2026-10-16): a tie is never a verdict; wrong blame counted over ALL scenarios."""
    tr = harness.truth(sid)
    tied = t.get("tied") or ([t["cause"]] if t.get("cause") else [])
    blamed = bool(t.get("cause"))
    if tr["outcome"] == "CONFIRMED":
        right = blamed and tied == [tr["cause"]]
        frac = (1.0 / len(tied)) if tr["cause"] in tied else 0.0
        wrong_frac = (1.0 - frac) if blamed else 0.0
        oc = right and t["outcome"] == "CONFIRMED"
    else:
        right, wrong_frac = not blamed, (1.0 if blamed else 0.0)
        oc = bool(t["outcome_correct"])
    return {"outcome_correct_strict": oc, "wrong_blame_frac": round(wrong_frac, 4), "wrong_blame_any": wrong_frac > 0}


def run(progress: bool = True) -> dict:
    t0 = time.perf_counter()
    trials: list[dict] = []
    log: list[dict] = []
    for arm in ARMS:
        for sid in harness.SCENARIOS:
            seeds = (42,) if (sid in DATA_SCENARIOS or arm == "N") else SEEDS
            for seed in seeds:
                spec = copy.deepcopy(scenario.load(sid))
                spec["seed"] = seed
                t = {"scenario": sid, "arm": arm, "seed": seed, **_arm(arm, sid, spec)}
                t.update(strict_fields(sid, t))
                keep = ("scenario", "arm", "seed", "outcome", "cause", "tied", "top1", "outcome_correct",
                        "outcome_correct_strict", "false_blame", "abstention_correct", "wrong_blame_frac",
                        "wrong_blame_any", "distractors_rejected", "seconds")
                trials.append({k: t.get(k) for k in keep})
                if progress:
                    print(f"[seeds] {arm} {sid} seed={seed}: {t['outcome']} {t.get('cause')} "
                          f"ok={t['outcome_correct_strict']}", file=sys.stderr, flush=True)
        harness._relieve_engine(f"scenario-seeds-{arm}", log)
    scenario.set_pipeline_mode("incident")
    return {"seeds": list(SEEDS), "trials": trials, "engine_pressure": log, "seconds": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    r = run()
    r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason})
    Path(a.out).write_text(json.dumps(r, indent=1, default=str) + "\n")
    for arm in ARMS:
        ts = [t for t in r["trials"] if t["arm"] == arm]
        print(arm, len(ts), "strict correct", sum(t["outcome_correct_strict"] for t in ts),
              "any wrong blame", sum(t["wrong_blame_any"] for t in ts))


if __name__ == "__main__":
    main()
