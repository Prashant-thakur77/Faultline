"""Decisive bench (PREREGISTRATION amendment 2026-10-16): worlds where the look-alike is itself faulty.

In the gate bench every decoy is healthy, so the origin check (G4) rejects it as well as G2/G5 do: removing one FalkorDB
algorithm never changed a blamed cause there. Here the look-alike's own component has a genuine fault (its deploy broke
it), so the origin check passes it and only the graph can tell it apart:
  g5_only            the look-alike reaches the alerting component only through best-effort edges (cap 0.02)
  anomalous_no_path  the look-alike has no directed failure path to the alerting component
Expected (fixed here, from the topology config, before any run): CONFIRMED, the true cause blamed, the look-alike
eliminated (by G5 / G2). The capability ladder (evals/ladder.py rungs) runs on these worlds, plus arms T and T+.

    PYTHONPATH=backend scripts/memguard.sh 4000 uv run python evals/decisive_bench.py --reason "…"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import baselines  # noqa: E402
import gate_bench  # noqa: E402
import ladder  # noqa: E402
import mismatch_eval  # noqa: E402

SEED = 20261121
PLAN = {"g5_only": 20, "anomalous_no_path": 20}
OUT = ROOT / "evals" / "results" / "decisive_bench.json"


def generate(plan: dict[str, int] = PLAN, seed: int = SEED) -> list[dict]:
    topo, rnd = gate_bench.Topo(), random.Random(seed)
    ids_rnd = random.Random(seed ^ 0x0BAD1D5)

    def opaque(n: int = 8) -> str:
        return "".join(ids_rnd.choice("0123456789abcdef") for _ in range(n))

    roots = [n for n in topo.nodes if len(topo.symptoms_of(n)) > 0 and topo.any[n]]
    cases: list[dict] = []
    for cat, n in plan.items():
        made = tries = 0
        while made < n:
            tries += 1
            if tries > 5000:
                raise RuntimeError(f"decisive bench: cannot generate {n} {cat} cases")
            c = rnd.choice(roots)
            t = rnd.choice(topo.symptoms_of(c))
            if cat == "g5_only":   # reaches t, but never over a synchronous chain; not downstream of the cause
                pool = [d for d in topo.nodes if d not in (c, t) and t in topo.any[d] and t not in topo.sync[d]
                        and d not in topo.any[c] and c not in topo.any[d]]
                gate = "G5"
            else:                  # no directed failure path to t at all; not downstream of the cause
                pool = [d for d in topo.nodes if d not in (c, t) and t not in topo.any[d] and d not in topo.any[c]]
                gate = "G2"
            if not pool:
                continue
            d = rnd.choice(sorted(pool))
            made += 1
            cause, look = f"D-{opaque()}", f"D-{opaque()}"
            inject = [{"change": cause, "target": c, "kind": "deploy", "at": "-3m", "title": f"{c}: change"},
                      {"change": look, "target": d, "kind": "deploy", "at": "-3m", "title": f"{d}: change"}]
            rnd.shuffle(inject)
            sid = f"C{opaque(6)}"
            spec = {"id": sid, "name": f"generated incident {sid.lower()}", "tenant": "acme", "onset": "anchor+3h",
                    "inject": inject,
                    "effects": [{"target": c, "error_rate": round(rnd.uniform(0.25, 0.6), 3), "from": "-2m", "change": cause},
                                {"target": d, "error_rate": round(rnd.uniform(0.25, 0.6), 3), "from": "-2m", "change": look}],
                    "seed": rnd.randrange(1, 10_000),
                    "alerts": [{"id": f"al-{opaque()}", "target": t, "metric": "error_rate", "at": "0m"}],
                    "report": gate_bench.BENCH_REPORT.format(target=t), "window_min": 30}
            cases.append({"id": f"dc{len(cases) + 1:03d}", "category": cat, "spec": spec, "symptom": t, "origin": c,
                          "lookalike": d,
                          "expected": {"outcome": "CONFIRMED", "cause": cause, "eliminated": {look: gate}}})
    return cases


def run(progress: bool = True) -> dict:
    import harness

    t0 = time.perf_counter()
    cases = generate()
    out: dict = {"seed": SEED, "cases": len(cases), "rungs": {}, "engine_pressure": []}
    for name, changes in ladder.RUNGS.items():
        with ladder._switched(changes):
            rows = [mismatch_eval.run_case(c, None) for c in cases]
        per = {}
        for cat in PLAN:
            rs = [r for r in rows if r["category"] == cat]
            per[cat] = {"cases": len(rs), "right_cause": sum(r["right_cause"] for r in rs),
                        "wrong_confident": sum(r["wrong_confident"] for r in rs), "abstained": sum(r["abstained"] for r in rs),
                        "correct": sum(r["correct"] for r in rs),
                        "decoys_by": {g: sum(1 for r in rs for v in r["decoys_by"].values() if v == g)
                                      for g in sorted({v for r in rs for v in r["decoys_by"].values()})}}
        out["rungs"][name] = {"by_category": per, "rows": [{k: r[k] for k in ("id", "category", "outcome", "blamed",
                                                                             "right_cause", "wrong_confident", "abstained",
                                                                             "decoys_by")} for r in rows]}
        if progress:
            print(f"[decisive] {name}: " + json.dumps({k: {kk: v[kk] for kk in ("right_cause", "wrong_confident", "abstained")}
                                                       for k, v in per.items()}), file=sys.stderr, flush=True)
        harness._relieve_engine(f"decisive-{name}", out["engine_pressure"])
    trow = []
    for c in cases:
        b = baselines.both(c)
        trow.append({"id": c["id"], "category": c["category"], "t": baselines.score(c["expected"], b["t"]),
                     "tplus": baselines.score(c["expected"], b["tplus"])})
    out["arms"] = {arm: {cat: {"right_strict": sum(r[arm]["right_strict"] for r in trow if r["category"] == cat),
                               "right_frac": round(sum(r[arm]["right_frac"] for r in trow if r["category"] == cat), 2),
                               "wrong_frac": round(sum(r[arm]["wrong_frac"] for r in trow if r["category"] == cat), 2)}
                         for cat in PLAN} for arm in ("t", "tplus")}
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    r = run()
    r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason})
    Path(a.out).write_text(json.dumps(r, indent=1, default=str) + "\n")
    print(json.dumps({k: v["by_category"] for k, v in r["rungs"].items()}, indent=1))
    print(json.dumps(r["arms"], indent=1))


if __name__ == "__main__":
    main()
