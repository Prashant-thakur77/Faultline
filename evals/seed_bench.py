"""New, never-generated seeds for the gate bench and the deep bench (PREREGISTRATION amendment 2026-10-16).

Same generators, graders and product path as evals/gate_bench.py and evals/deep_bench.py. Per world it also records
whether the gate accepted a change NOT_CONFIDENT (a bystander acceptance: correct by outcome on abstain cases, counted
separately) and the blames of arms T and T+ (evals/baselines.py). Writes evals/results/seed_bench.json, folded into
latest.json by evals/report.py (keys seeds.*). The engine is compacted between seeds (harness._relieve_engine).

    PYTHONPATH=backend scripts/memguard.sh 4000 uv run python evals/seed_bench.py --reason "M18 phase 2: first run"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import baselines  # noqa: E402
import deep_bench  # noqa: E402
import gate_bench  # noqa: E402

GATE_SEEDS = (20261101, 20261102, 20261103)
DEEP_SEEDS = (20261111, 20261112, 20261113)
OUT = ROOT / "evals" / "results" / "seed_bench.json"
# addendum 2026-10-16 (item 2): 8 more deep-bench seeds, 1,120 worlds, never generated before; own side file
DEEP_SEEDS2 = tuple(range(20261141, 20261149))
OUT2 = ROOT / "evals" / "results" / "seed_bench2.json"
RELIEVE_EVERY = 35   # worlds between engine-pressure checks (each world makes two clean rooms: product + T/T+)


def run_world(c: dict, kind: str) -> dict:
    r = gate_bench.run_case(c)
    g, exp = r["got"], c["expected"]
    blamed = g["cause"]
    tt = baselines.both(c)
    row = {"id": c["id"], "category": c["category"], "outcome": g["outcome"], "blamed": blamed,
           "accepted_not_confident": g.get("accepted_not_confident"),
           "has_cause": exp["outcome"] == "CONFIRMED" and exp.get("cause") is not None,
           "right_cause": exp["outcome"] == "CONFIRMED" and blamed == exp["cause"],
           "wrong_confident": blamed is not None and blamed != exp.get("cause"),
           "abstained": blamed is None and g["outcome"] in gate_bench.ABSTAIN_OK,
           "correct": r["correct"],
           "t": baselines.score(exp, tt["t"]), "tplus": baselines.score(exp, tt["tplus"]),
           "tplus_outcome": tt["tplus"]["outcome"]}
    if kind == "deep":
        row["hops"] = c.get("hops")
        row["ok"] = ((blamed is None and g["outcome"] in gate_bench.ABSTAIN_OK) if exp["cause"] is None else
                     (blamed == exp["cause"] or (c["category"] in deep_bench.ABSTAIN_FINE and blamed is None
                                                 and g["outcome"] in gate_bench.ABSTAIN_OK)))
    # strict: an abstain/control case where the gate accepted a bystander change NOT_CONFIDENT is not a clean verdict
    row["correct_strict"] = r["correct"] and not (exp["outcome"] != "CONFIRMED" and g.get("accepted_not_confident"))
    return row


def summary(rows: list[dict]) -> dict:
    def s(arm: str, k: str) -> float:
        return round(sum(r[arm][k] for r in rows), 2)
    cause_rows = [r for r in rows if r["has_cause"]]
    out = {"cases": len(rows), "cause_cases": len(cause_rows), "correct": sum(r["correct"] for r in rows),
           "correct_strict": sum(r["correct_strict"] for r in rows),
           "bystander_not_confident": sum(1 for r in rows if r["accepted_not_confident"]),
           "right_cause": sum(r["right_cause"] for r in rows), "wrong_confident": sum(r["wrong_confident"] for r in rows),
           "abstained": sum(r["abstained"] for r in rows)}
    if rows and "ok" in rows[0]:
        out["ok"] = sum(r["ok"] for r in rows)
    for arm in ("t", "tplus"):
        out[arm] = {"right_strict": sum(r[arm]["right_strict"] for r in cause_rows),
                    "right_frac": round(sum(r[arm]["right_frac"] for r in cause_rows), 2),
                    "wrong_frac": s(arm, "wrong_frac"), "wrong_any": sum(1 for r in rows if r[arm]["wrong_frac"] > 0),
                    "abstained": sum(r[arm]["abstained"] for r in rows)}
    return out


def run(progress: bool = True) -> dict:
    import harness

    t0 = time.perf_counter()
    out: dict = {"gate": {}, "deep": {}, "engine_pressure": []}
    for kind, seeds, gen in (("gate", GATE_SEEDS, gate_bench.generate), ("deep", DEEP_SEEDS, deep_bench.generate)):
        for seed in seeds:
            cases = gen(seed=seed)
            rows = []
            for c in cases:
                rows.append(run_world(c, kind))
                if progress:
                    r = rows[-1]
                    print(f"[seeds] {kind} {seed} {r['id']} {r['category']}: {r['outcome']} right={r['right_cause']} "
                          f"wc={r['wrong_confident']} T+={r['tplus_outcome']}", file=sys.stderr, flush=True)
            cats = sorted({r["category"] for r in rows})
            out[kind][str(seed)] = {"all": summary(rows), "by_category": {k: summary([r for r in rows if r["category"] == k])
                                                                         for k in cats}, "rows": rows}
            harness._relieve_engine(f"{kind}-{seed}", out["engine_pressure"])
    for kind in ("gate", "deep"):
        allrows = [r for v in out[kind].values() for r in v["rows"]]
        out[f"{kind}_pooled"] = summary(allrows)
    # T and T+ on the HEADLINE deep bench (fresh seed 20261016, the 140 worlds the README quotes): comparators only,
    # so the product's headline numbers stay those of the recorded run
    trows = []
    for c in deep_bench.generate(seed=deep_bench.FRESH_SEED):
        b = baselines.both(c)
        trows.append({"id": c["id"], "category": c["category"], "has_cause": c["expected"]["cause"] is not None,
                      "t": baselines.score(c["expected"], b["t"]), "tplus": baselines.score(c["expected"], b["tplus"]),
                      "tplus_outcome": b["tplus"]["outcome"]})
    out["deep_fresh_baselines"] = {"seed": deep_bench.FRESH_SEED, "cases": len(trows),
                                   "cause_cases": sum(r["has_cause"] for r in trows),
                                   **{arm: {"right_strict": sum(r[arm]["right_strict"] for r in trows if r["has_cause"]),
                                            "right_frac": round(sum(r[arm]["right_frac"] for r in trows if r["has_cause"]), 2),
                                            "wrong_any": sum(1 for r in trows if r[arm]["wrong_frac"] > 0),
                                            "wrong_frac": round(sum(r[arm]["wrong_frac"] for r in trows), 2),
                                            "abstained": sum(r[arm]["abstained"] for r in trows)} for arm in ("t", "tplus")},
                                   "rows": trows}
    harness._relieve_engine("deep-fresh-baselines", out["engine_pressure"])
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def classify_acceptances(rows: list[dict], cases: list[dict]) -> dict:
    """A run that ends NOT_CONFIDENT may still ACCEPT a change (not confidently). Split those acceptances: the expected
    cause, another genuinely faulty change, or a bystander with no fault of its own (M18 audit)."""
    by_id = {c["id"]: c for c in cases}
    out = {"expected_cause": 0, "other_faulty_change": 0, "bystander": 0}
    for r in rows:
        a = r.get("accepted_not_confident")
        if not a:
            continue
        c = by_id[r["id"]]
        faulty = {e.get("change") for e in c["spec"]["effects"] if e.get("change")}
        out["expected_cause" if a == c["expected"]["cause"] else ("other_faulty_change" if a in faulty else "bystander")] += 1
    return out


def headline_deep(progress: bool = True) -> dict:
    """The headline deep bench (fresh seed 20261016) re-run with per-world rows: must reproduce run_0033's numbers
    (the bench is deterministic), and records the not-confident acceptances the run file dropped."""
    cases = deep_bench.generate(seed=deep_bench.FRESH_SEED)
    rows = []
    for c in cases:
        rows.append(run_world(c, "deep"))
        if progress:
            r = rows[-1]
            print(f"[headline] {r['id']} {r['category']}: {r['outcome']} right={r['right_cause']} "
                  f"accepted_nc={r['accepted_not_confident']}", file=sys.stderr, flush=True)
    cats = sorted({r["category"] for r in rows})
    return {"seed": deep_bench.FRESH_SEED, "all": summary(rows) | {"acceptances": classify_acceptances(rows, cases)},
            "by_category": {k: summary([r for r in rows if r["category"] == k]) | {
                "acceptances": classify_acceptances([r for r in rows if r["category"] == k], cases)} for k in cats},
            "rows": rows}


def run_seeds2(out_path: Path, reason: str, progress: bool = True) -> dict:
    """Addendum 2026-10-16 item 2: the deep bench on DEEP_SEEDS2 through run_world (product + T + T+). Each seed is
    written to the side file as it completes, so an interrupted run resumes at the next seed."""
    import harness

    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    out.setdefault("deep", {})
    out.setdefault("engine_pressure", [])
    out.setdefault("runs", []).append({"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason})
    out["deep_seeds"] = list(DEEP_SEEDS2)
    for seed in DEEP_SEEDS2:
        if str(seed) in out["deep"]:
            continue
        t0 = time.perf_counter()
        rows = []
        for i, c in enumerate(deep_bench.generate(seed=seed)):
            rows.append(run_world(c, "deep"))
            if progress:
                r = rows[-1]
                print(f"[seeds2] {seed} {r['id']} {r['category']}: {r['outcome']} right={r['right_cause']} "
                      f"wc={r['wrong_confident']} T+={r['tplus_outcome']}", file=sys.stderr, flush=True)
            if (i + 1) % RELIEVE_EVERY == 0:
                harness._relieve_engine(f"seeds2-{seed}-{i + 1}", out["engine_pressure"])
        cats = sorted({r["category"] for r in rows})
        out["deep"][str(seed)] = {"all": summary(rows), "by_category": {k: summary([r for r in rows if r["category"] == k])
                                                                       for k in cats},
                                  "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}
        out["deep_pooled"] = summary([r for v in out["deep"].values() for r in v["rows"]])
        out["complete"] = all(str(x) in out["deep"] for x in DEEP_SEEDS2)
        out["runs"][-1]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=1, default=str) + "\n")
        tmp.replace(out_path)
        harness._relieve_engine(f"seeds2-{seed}", out["engine_pressure"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True, help="why this run (logged in the side file; PREREGISTRATION 2026-10-16)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--headline-deep", action="store_true",
                    help="re-run the headline deep bench with rows → evals/results/deep_fresh_detail.json")
    ap.add_argument("--seeds2", action="store_true",
                    help="the 8 deep-bench seeds of addendum 2026-10-16 (1,120 worlds) → evals/results/seed_bench2.json")
    a = ap.parse_args()
    if a.seeds2:
        r = run_seeds2(OUT2, a.reason)
        print(json.dumps(r.get("deep_pooled"), indent=1))
        return
    if a.headline_deep:
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        r = headline_deep()
        r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason})
        (ROOT / "evals" / "results" / "deep_fresh_detail.json").write_text(json.dumps(r, indent=1, default=str) + "\n")
        print(json.dumps(r["all"], indent=1))
        return
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    r = run()
    r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason,
              "gate_seeds": list(GATE_SEEDS), "deep_seeds": list(DEEP_SEEDS)})
    Path(a.out).write_text(json.dumps(r, indent=1, default=str) + "\n")
    print(json.dumps({"gate_pooled": r["gate_pooled"], "deep_pooled": r["deep_pooled"]}, indent=1))


if __name__ == "__main__":
    main()
