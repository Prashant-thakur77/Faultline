"""Robustness: where Faultline breaks (PREREGISTRATION amendment 2026-10-13).

The 100 held-out gate-bench worlds (seed 20261015), one knob turned at a time, everything else as shipped:
  duplicates    every alert repeated ×2 / ×5 / ×10 (new ids, same target, within a minute)
  missing       error-rate windows deleted for 20% / 50% / 80% of the monitored components (seeded choice; the
                cause's own component is included whenever drawn)
  noise         the world's per-minute noise ×2 / ×4
  intermittent  the cause's effect on for one minute, off for the next (an unseen fault shape)
Graded with the bench's own expected verdicts. The breaking point of a knob is its first setting where correct drops
by 5 or more cases from the unperturbed run, or wrong-confident is above 0.

    PYTHONPATH=backend uv run python evals/robustness.py [--knobs duplicates,missing,noise,intermittent] [--out FILE]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
import time
import uuid
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402
from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator, run_incident  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402

SEED = 20261015
KNOBS = {"duplicates": [2, 5, 10], "missing": [0.2, 0.5, 0.8], "noise": [2, 4], "intermittent": [1]}
# PREREGISTRATION amendment 2026-10-16: the same knobs as curves, plus the fault's size (every effect's error rate scaled)
CURVES = {"noise": [2, 4, 8, 16, 32, 64], "missing": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
          "effect": [0.5, 0.25, 0.1, 0.05, 0.025]}


def _spec(case: dict, knob: str, level) -> dict:
    spec = copy.deepcopy(case["spec"])
    if knob == "duplicates":
        extra = []
        for a in spec["alerts"]:
            for i in range(1, int(level)):
                extra.append({**a, "id": f"{a['id']}-dup{i}", "at": "1m" if i % 2 else "0m"})
        spec["alerts"] = spec["alerts"] + extra
    elif knob == "noise":
        spec["noise"] = 0.15 * float(level)
    elif knob == "effect":
        spec["effects"] = [{**e, "error_rate": round(float(e["error_rate"]) * float(level), 5)} for e in spec.get("effects", [])]
    elif knob == "intermittent":
        out = []
        for e in spec.get("effects", []):
            for m in range(-2, 8, 2):  # on [-2m,-1m), [0m,1m), [2m,3m), … : one minute on, one off
                out.append({**e, "from": f"{m}m", "until": f"{m + 1}m"})
        spec["effects"] = out
    return spec


def _run(case: dict, knob: str | None, level) -> dict:
    spec = _spec(case, knob, level) if knob else case["spec"]
    db = gclient.engine()
    p = scenario.prepare(spec["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        if knob == "missing":
            ro = RO(p.tenant, p.graph)
            comps = sorted({r["src"] for r in ro.run("Q-SIM-1", {}).rows} | {r["dst"] for r in ro.run("Q-SIM-1", {}).rows})
            rnd = random.Random(f"{case['spec']['seed']}:missing:{level}")
            drop = rnd.sample(comps, int(round(len(comps) * float(level))))
            writes.perturb_model(db.select_graph(p.graph), drop_windows=drop)
        r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                           symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                           run_id=p.run_id, window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(db, p.graph)
    blamed = r.cause_id if r.outcome == "CONFIRMED" else None
    exp = case["expected"]
    got = {"outcome": r.outcome, "cause": blamed, "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in r.sweep}}
    return {"id": case["id"], "category": case["category"], "outcome": r.outcome, "blamed": blamed,
            "wrong_confident": blamed is not None and (exp["outcome"] != "CONFIRMED" or blamed != exp["cause"]),
            "abstained": blamed is None and r.outcome in gate_bench.ABSTAIN_OK,
            **gate_bench.detail(exp, r.outcome, blamed, got["sweep"]), **gate_bench.grade(exp, got)}


def _summary(rows: list[dict]) -> dict:
    return {"correct": sum(r["correct"] for r in rows), "wrong_confident": sum(r["wrong_confident"] for r in rows),
            "abstained": sum(r["abstained"] for r in rows), "cases": len(rows)}


def run_curves(seed: int = SEED, progress: bool = True) -> dict:
    """Every curve point on the same 100 worlds, compacting the engine between points (harness._relieve_engine)."""
    import harness

    t0 = time.perf_counter()
    cases = gate_bench.generate(seed=seed)
    log: list[dict] = []

    def point(knob, level):
        rows = [_run(c, knob, level) for c in cases]
        b = gate_bench.buckets(rows, cases)
        s = _summary(rows) | {"right_cause": b["right_cause"], "cause_cases": b["confirm_cases"],
                              "other": b["other"], "abstained_not_correct": b["abstained_not_correct"]}
        harness._relieve_engine(f"robustness-{knob}-{level}", log)
        if progress:
            print(f"[curves] {knob}={level}: {s}", file=sys.stderr, flush=True)
        return s

    out: dict = {"seed": seed, "baseline": point(None, None), "curves": {}}
    for knob, levels in CURVES.items():
        out["curves"][knob] = {str(lv): point(knob, lv) for lv in levels}
    out["engine_pressure"] = log
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def run(knobs=tuple(KNOBS), seed: int = SEED, progress: bool = True) -> dict:
    t0 = time.perf_counter()
    cases = gate_bench.generate(seed=seed)
    base_rows = [_run(c, None, None) for c in cases]
    base = _summary(base_rows) | {"buckets": gate_bench.buckets(base_rows, cases)}
    out: dict = {"seed": seed, "baseline": base, "knobs": {}}
    for knob in knobs:
        levels = {}
        breaking = None
        for level in KNOBS[knob]:
            rows = [_run(c, knob, level) for c in cases]
            s = _summary(rows) | {"buckets": gate_bench.buckets(rows, cases)}
            s["wrong"] = [{k: r[k] for k in ("id", "category", "outcome", "blamed")} for r in rows if r["wrong_confident"]]
            levels[str(level)] = s
            if breaking is None and (base["correct"] - s["correct"] >= 5 or s["wrong_confident"] > 0):
                breaking = level
            if progress:
                print(f"[robustness] {knob}={level}: correct {s['correct']}, wrong-confident {s['wrong_confident']}, "
                      f"abstained {s['abstained']}", file=sys.stderr, flush=True)
        out["knobs"][knob] = {"levels": levels, "breaking_point": breaking}
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--knobs", default=",".join(KNOBS))
    ap.add_argument("--out")
    ap.add_argument("--curves", action="store_true", help="the 2026-10-16 curves → evals/results/robustness_curves.json")
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.curves:
        if not a.reason:
            raise SystemExit("--curves needs --reason")
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        r = run_curves()
        r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason})
        Path(a.out or ROOT / "evals" / "results" / "robustness_curves.json").write_text(json.dumps(r, indent=1) + "\n")
        return
    r = run(tuple(k for k in a.knobs.split(",") if k))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
