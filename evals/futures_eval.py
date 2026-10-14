"""Futures eval (M14 #1): does a containment candidate's predicted future match what the world then does?

The prediction is the product's: the `futures` tool in the plan (Q-FUTURE-1 on one GRAPH.COPY branch per candidate:
the origin's MEASURED excess × its path transfer over the edges the candidate leaves, the gate's upper-bound model).
The outcome is the world's: for every candidate the plan read (each single min-cut edge, the whole cut, removing the
origin's fault, changing nothing) the simulator (sim/telemetry.py, with the scenario's own injected effects, which the
predictor never sees) writes 3 minutes of telemetry after that candidate is in place, each candidate in its own time
slot on the run's own throwaway graph, and VERIFY's band rule (`in_band`, the same function) decides whether every
symptom is back. A candidate that removes the origin drops the effects its cause produced, as a rollback does in VERIFY.

Reported: agreement k/n over the definite predictions; false assurance (predicted to contain, the world does not:
the model is an upper bound, so this should be 0); conservative misses (predicted not to contain, the world does);
unknown predictions (named, not counted in k/n).

    PYTHONPATH=backend uv run python evals/futures_eval.py [--scenarios S1,S3]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "backend"))

from faultline import scenario  # noqa: E402
from faultline.agent.datatools import band_from, in_band  # noqa: E402
from faultline.agent.loop import BaselineInvestigator  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.sim.telemetry import simulate  # noqa: E402

SCENARIOS = ["S1", "S2", "S3", "S4D", "S4S", "S12", "S1b", "S3b"]
MINUTE = 60_000
SLOT_MIN = 10   # each candidate's world runs in its own 10-minute slot after the plan (no shared windows)
BENCH_SEED = 20261015  # the gate bench's held-out worlds (never tuned on)


def _removed(e, cause: str | None, origin: str) -> bool:
    """The effects a fix at the origin removes: those its confirmed cause produced (VERIFY's rollback rule), or, with
    no confirmed cause (an inferred origin), those on the origin component itself."""
    return getattr(e, "change", None) == cause if cause else e.target == origin


def _world(ro: RO, g, *, cand: dict, effects: list, cause: str | None, symptoms: list[str], onset: int, at: int,
           world_seed: int) -> dict:
    """Apply one candidate to the world at `at` and judge every symptom with VERIFY's band rule."""
    live = [e for e in effects if not (cand.get("removes_origin") and _removed(e, cause, cand["origin"]))]
    cuts = {(u, v) for u, v in cand.get("cuts") or []}
    simulate(g, ro, onset_ms=onset, effects=live, cut_edges=cuts, start_ms=at + MINUTE, minutes=3, seed=int(at % 10_000),
             base_seed=world_seed)
    per = {}
    for t in symptoms:
        after = [r["value"] for r in ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": at + MINUTE,
                                                       "until": at + 4 * MINUTE}).rows]
        base_vals = [r["value"] for r in ro.run("Q-MW-1", {"target": t, "metric": "error_rate", "since": onset - 30 * MINUTE,
                                                           "until": onset - 5 * MINUTE}).rows]
        if len(after) != 3 or not base_vals:
            per[t] = {"ok": None, "after": after}
            continue
        base, band = sum(base_vals) / len(base_vals), band_from(base_vals)
        per[t] = {"ok": all(in_band(v, base, band) for v in after), "after": [round(v, 5) for v in after],
                  "baseline": round(base, 5)}
    oks = [x["ok"] for x in per.values()]
    world = None if None in oks or not oks else ("contains" if all(oks) else "does_not_contain")
    return {"world": world, "symptoms": per}


def _evaluate(p, r, label: str) -> dict:
    """Every candidate the run's plan read, applied to the world in its own slot on the run's own graph."""
    fut = (r.post_gate or {}).get("futures") or {}
    rows = fut.get("rows") or []
    if not rows:
        return {"scenario": label, "outcome": r.outcome, "skipped": "no futures read (no plan, or no symptoms)"}
    g, ro = gclient.engine().select_graph(p.graph), RO(p.tenant, p.graph)
    effects = scenario.effects_of(p.scenario, p.onset_ms)
    out = []
    for i, x in enumerate(rows):
        at = p.onset_ms + (15 + i * SLOT_MIN) * MINUTE
        w = _world(ro, g, cand=x, effects=effects, cause=r.cause_id, symptoms=p.symptoms, onset=p.onset_ms, at=at,
                   world_seed=int(p.scenario.get("seed", 42)))
        pred = x["predicted"]
        agree = None if pred == "unknown" or w["world"] is None else (pred == w["world"])
        out.append({"key": x["key"], "predicted": pred, "world": w["world"], "agrees": agree,
                    "exposed": x.get("exposed") or [], "line": x["line"], "world_symptoms": w["symptoms"]})
    return {"scenario": label, "outcome": r.outcome, "cause": r.cause_id, "evidence_id": fut.get("evidence_id"),
            "candidates": out}


def run_scenario(sid: str) -> dict:
    p, r = anyio.run(lambda: scenario.run(sid, BaselineInvestigator(), set_mode=False, keep=True))
    try:
        return _evaluate(p, r, sid)
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def run_bench_case(case: dict) -> dict:
    """One generated gate-bench world (evals/gate_bench.py: random topology, caps and call shares) through the
    product, then its futures against that world. The bench's grader-only fields are not read here."""
    import uuid

    from faultline.agent.loop import run_incident

    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                           symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                           run_id=p.run_id, window_min=p.scenario.get("window_min")))
        return _evaluate(p, r, case["id"])
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def kind_of(key: str) -> str:
    """cut: a measured prediction on a branch (one min-cut edge, or the whole cut); remove_origin: residual 0 by
    assumption (true by construction whenever the cause is right); no_change: the fault as measured (near trivial)."""
    return key if key in ("remove_origin", "no_change") else "cut"


def _counts(cands: list[dict]) -> dict:
    definite = [c for c in cands if c["agrees"] is not None]
    return {"candidates": len(cands), "definite": len(definite), "agree": sum(1 for c in definite if c["agrees"]),
            "false_assurance": sum(1 for c in definite if c["predicted"] == "contains" and c["world"] != "contains"),
            "conservative": sum(1 for c in definite if c["predicted"] == "does_not_contain" and c["world"] == "contains"),
            "unknown": sum(1 for c in cands if c["predicted"] == "unknown"),
            "world_unreadable": sum(1 for c in cands if c["predicted"] != "unknown" and c["world"] is None),
            "predicted_contains": sum(1 for c in definite if c["predicted"] == "contains"),
            "predicted_not": sum(1 for c in definite if c["predicted"] == "does_not_contain")}


def summarise(res: list[dict]) -> dict:
    """Totals, then per candidate kind: the `cut` numbers are the measured predictions (the headline); the other two
    are reported so the totals are not read as more than they are."""
    cands = [c for x in res for c in x.get("candidates", [])]
    out = _counts(cands) | {"scenarios": len(res), "scenarios_read": sum(1 for x in res if x.get("candidates")),
                            "rows": res}
    for k in ("cut", "remove_origin", "no_change"):
        out[k] = _counts([c for c in cands if kind_of(c["key"]) == k])
    return out


def run(scenarios: list[str] | None = None, bench_seed: int | None = BENCH_SEED, progress: bool = True) -> dict:
    """The scenario suite, then (unless bench_seed is None) every gate-bench world the product confirms or infers an
    origin for. Each part is summarised on its own."""
    t0 = time.perf_counter()

    def say(x: dict) -> None:
        if progress:
            got = x.get("skipped") or ", ".join(f"{c['key']}: {c['predicted']}/{c['world']}" for c in x["candidates"])
            print(f"[futures] {x['scenario']} {x['outcome']}: {got}", file=sys.stderr, flush=True)

    res = []
    for sid in scenarios or SCENARIOS:
        res.append(run_scenario(sid))
        say(res[-1])
    out = summarise(res)
    if bench_seed is not None:
        if __import__("importlib.util").util.find_spec("gate_bench") is None:
            sys.path.insert(0, str(ROOT / "evals"))
        import gate_bench

        bench = []
        for case in gate_bench.generate(seed=bench_seed):
            bench.append(run_bench_case(case))
            say(bench[-1])
        out["bench"] = summarise(bench) | {"seed": bench_seed, "cases": len(bench)}
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--no-bench", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(a.scenarios.split(","), bench_seed=None if a.no_bench else BENCH_SEED)
    for name, x in [("scenarios", r)] + ([("gate-bench worlds", r["bench"])] if "bench" in r else []):
        for k in ("cut", "remove_origin", "no_change"):
            y = x[k]
            print(f"futures on {name} [{k}]: {y['agree']}/{y['definite']} agree; false assurance {y['false_assurance']}; "
                  f"conservative {y['conservative']}; unknown {y['unknown']} ({y['candidates']} candidates)")
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
