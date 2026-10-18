"""Model-mismatch robustness (PREREGISTRATION amendment 2026-10-13).

Every other gate number is measured on worlds whose telemetry was generated over the same topology and capacities the
gate reads. Here the graph is made WRONG about the world: the 100 held-out gate-bench worlds (seed 20261015) are
prepared as usual (telemetry from the TRUE topology), then the graph the product reads is perturbed, per case with
its own seeded stream (case seed XOR 0x313, per variant):
  caps    every PROPAGATES_TO.cap × U(0.5, 1.5), clipped to [0.01, 1.0]
  hidden  one random PROPAGATES_TO edge deleted (the world still propagates over it)
  stale   one PROPAGATES_TO edge added where none exists and no cycle forms, cap U(0.1, 1.0)
  all     the three together
Graded with the bench's own expected verdicts and grader (unchanged). Reported per variant: correct, wrong-confident
(a CONFIRMED blame of another change than the expected cause, or any confirmed blame where the expected outcome is
an abstention or no incident), abstention, and the cases that flipped from correct.

Also arm T (telemetry only, no topology) on the same 100 worlds, unperturbed: blame the window's change whose own
component shows the largest measured excess; ties 1/k; it never abstains.

    PYTHONPATH=backend uv run python evals/mismatch_eval.py [--variants caps,hidden,stale,all] [--out FILE]
"""

from __future__ import annotations

import argparse
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
from faultline.agent.weights import weights  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402

SEED = 20261015
VARIANTS = ("caps", "hidden", "stale", "all")


def _perturbation(ro: RO, rnd: random.Random, variant: str) -> dict:
    """What to change in the model graph (reads only; the write is writes.perturb_model)."""
    view = ro.run("Q-SIM-1", {})
    if view.truncated:
        raise RuntimeError("Q-SIM-1 truncated: the bench topology is larger than one read")
    edges = sorted({(r["src"], r["dst"]): float(r["cap"]) for r in view.rows}.items())
    out: dict = {}
    if variant in ("caps", "all"):
        out["caps"] = [[u, v, round(min(1.0, max(0.01, c * rnd.uniform(0.5, 1.5))), 4)] for (u, v), c in edges]
    if variant in ("hidden", "all"):
        u, v = rnd.choice(edges)[0]
        out["delete"] = [[u, v]]
    if variant in ("stale", "all"):
        nodes = sorted({x for (u, v), _ in edges for x in (u, v)})
        have = {e for e, _ in edges}
        for _ in range(200):
            u, v = rnd.sample(nodes, 2)
            if (u, v) in have or (v, u) in have:
                continue
            reach = ro.run("Q-WHATIF-1", {"failing": v}).rows
            if u in set((reach[0]["reached"] if reach else [])):  # v already reaches u: u → v would close a cycle
                continue
            out["add"] = [[u, v, round(rnd.uniform(0.1, 1.0), 3)]]
            break
    return out


def run_case(case: dict, variant: str | None) -> dict:
    """One bench world through the product; `variant` None = the unperturbed graph (the bench itself)."""
    t0 = time.perf_counter()
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        change = {}
        if variant:
            rnd = random.Random(f"{int(case['spec']['seed']) ^ 0x313}:{variant}")
            change = _perturbation(RO(p.tenant, p.graph), rnd, variant)
            change["applied"] = writes.perturb_model(gclient.engine().select_graph(p.graph), caps=change.get("caps"),
                                                     delete=change.get("delete"), add=change.get("add"))
        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                             run_id=p.run_id, window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    blamed = res.cause_id if res.outcome == "CONFIRMED" else None
    got = {"outcome": res.outcome, "cause": blamed, "error": res.error,
           "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in res.sweep}}
    exp = case["expected"]
    wrong_confident = blamed is not None and (exp["outcome"] != "CONFIRMED" or blamed != exp["cause"])
    return {"id": case["id"], "category": case["category"], "outcome": res.outcome, "blamed": blamed,
            "wrong_confident": wrong_confident, "abstained": blamed is None and res.outcome in gate_bench.ABSTAIN_OK,
            "perturbation": {k: change.get(k) for k in ("delete", "add", "applied")},
            **gate_bench.detail(exp, res.outcome, blamed, got["sweep"]),
            **gate_bench.grade(exp, got), "seconds": round(time.perf_counter() - t0, 2)}


def arm_t_case(case: dict) -> dict:
    """Arm T on one bench world (unperturbed): the window's change whose component shows the largest excess."""
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        ro = RO(p.tenant, p.graph)
        changes = ro.run("Q-SUS-2", {"onset": p.onset_ms, "window_ms": 30 * 60_000}).rows
        iw = weights()["intake"]
        b0, b1 = p.onset_ms - int(iw["baseline_min"]) * 60_000, p.onset_ms - int(iw["baseline_gap_min"]) * 60_000
        excess = {}
        for c in changes:
            base = [r["value"] for r in ro.run("Q-MW-1", {"target": c["target"], "metric": "error_rate", "since": b0,
                                                          "until": b1}).rows]
            after = [r["value"] for r in ro.run("Q-MW-1", {"target": c["target"], "metric": "error_rate",
                                                           "since": p.onset_ms, "until": p.onset_ms + 10 * 60_000}).rows]
            excess[c["deploy"]] = round(max(after) - sum(base) / len(base), 5) if base and after else 0.0
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    exp = case["expected"]
    if not excess:
        return {"id": case["id"], "category": case["category"], "score": 1.0 if exp["outcome"] == "NO_INCIDENT" else 0.0,
                "blamed": []}
    best = max(excess.values())
    tied = sorted(c for c, v in excess.items() if v == best)
    score = (1.0 / len(tied) if exp["cause"] in tied else 0.0) if exp["outcome"] == "CONFIRMED" else 0.0
    return {"id": case["id"], "category": case["category"], "score": score, "blamed": tied}


def summarise(rows: list[dict], base: dict[str, bool] | None = None) -> dict:
    n = len(rows)
    out = {"cases": n, "correct": sum(r["correct"] for r in rows), "wrong_confident": sum(r["wrong_confident"] for r in rows),
           "abstained": sum(r["abstained"] for r in rows), "errors": sum(1 for r in rows if r.get("error"))}
    out["wrong_confident_rate"] = round(out["wrong_confident"] / n, 4) if n else None
    if base is not None:
        out["flipped_from_correct"] = sorted(r["id"] for r in rows if base.get(r["id"]) and not r["correct"])
    return out


def run(variants=VARIANTS, seed: int = SEED, progress: bool = True) -> dict:
    t0 = time.perf_counter()
    cases = gate_bench.generate(seed=seed)
    base_rows = [run_case(c, None) for c in cases]
    base = {r["id"]: r["correct"] for r in base_rows}
    out = {"seed": seed, "baseline": summarise(base_rows), "variants": {}}
    if progress:
        print(f"[mismatch] baseline: {out['baseline']}", file=sys.stderr, flush=True)
    for v in variants:
        rows = [run_case(c, v) for c in cases]
        out["variants"][v] = summarise(rows, base) | {
            "wrong": [{k: r[k] for k in ("id", "category", "outcome", "blamed", "perturbation", "why")}
                      for r in rows if r["wrong_confident"]]}
        if progress:
            print(f"[mismatch] {v}: " + json.dumps({k: x for k, x in out['variants'][v].items() if k != 'wrong'}),
                  file=sys.stderr, flush=True)
    t_rows = [arm_t_case(c) for c in cases]
    conf = [r for r in t_rows if any(c["id"] == r["id"] and c["expected"]["outcome"] == "CONFIRMED" for c in cases)]
    out["arm_t"] = {"cases": len(t_rows), "score": round(sum(r["score"] for r in t_rows), 2),
                    "confirm_cases": len(conf), "confirm_score": round(sum(r["score"] for r in conf), 2),
                    "wrong_blame": sum(1 for r in t_rows if r["blamed"] and r["score"] == 0.0),
                    "by_category": {cat: round(sum(r["score"] for r in t_rows if r["category"] == cat), 2)
                                    for cat in sorted({r["category"] for r in t_rows})},
                    "rows": [{"id": r["id"], "score": r["score"]} for r in t_rows]}   # per case (perf_vs_flat depth curve)
    if progress:
        print(f"[mismatch] arm T: {out['arm_t']}", file=sys.stderr, flush=True)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(tuple(v for v in a.variants.split(",") if v))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
