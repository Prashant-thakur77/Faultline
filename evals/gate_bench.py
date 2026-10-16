"""Gate bench: generated gate cases on clean-room copies of golden_acme ("gate verdicts k/k").

Each case is a small incident written in the scenarios.yaml shape and run through the PRODUCT path
(`scenario.prepare(spec=…)` → `run_incident` with the deterministic investigator) on its own fresh GRAPH.COPY of
golden_acme, deleted afterwards. The expected verdict is decided by THIS file, from the topology config
(data/topology/otel-demo.yaml), before anything runs; it never comes from the engine or the gate, so a template or
gate bug cannot make both sides agree. The cases are drawn from a seeded RNG and are not filtered by outcome.

Categories (each case: one true cause, or none, plus same-minute look-alike deploys):
  G2       true cause + 1–2 distractors with NO failure path to the alerting component  → CONFIRMED, each "G2"
  G5       true cause + a distractor whose every path crosses a best-effort (cap 0.02) edge → CONFIRMED, "G5"
  origin   true cause + a HEALTHY distractor with a synchronous path and full capacity     → CONFIRMED, "G4 origin"
  abstain  a component degrades with NO change on it (+ 0–2 benign deploys)               → abstain: no change blamed,
                                                                                            NOT_CONFIDENT or UNKNOWN_ESCALATED
                                                                                            (the harness's abstention_correct)
  control  1–2 benign deploys, an alert, nothing degraded                                 → NO_INCIDENT
A verdict is correct when the outcome and the blamed change match and, for CONFIRMED cases, every distractor is
eliminated by the expected gate. Oracle reachability below is grader code over the config file (the product's
reachability runs only in FalkorDB).

    make bench                                                       # 100 cases → evals/results/gate_bench.json
    PYTHONPATH=backend uv run python evals/gate_bench.py --fast --check-recorded   # 20 of them (judge-check, CI)
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
import yaml

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator, run_incident  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402

TOPOLOGY = ROOT / "data" / "topology" / "otel-demo.yaml"
PLAN = {"G2": 25, "G5": 20, "origin": 20, "abstain": 20, "control": 15}   # 100 cases
FAST = {"G2": 4, "G5": 4, "origin": 4, "abstain": 4, "control": 4}       # 20 cases
SEED = 20261013
EXPECT_REASON = {"G2": "G2", "G5": "G5", "origin": "G4 origin"}
BENCH_REPORT = "{target} errors are elevated"  # intake text; its vector is precomputed by data/gen/embed.py


# ------------------------------------------------------------------ oracle (topology config, not the engine)
class Topo:
    def __init__(self, path: Path = TOPOLOGY, config: dict | None = None):
        """`config`: the same shape as the topology YAML ({services, datastores, calls}) from another source (the globex
        generator, evals/world_bench.py --tenant globex); default: acme's committed config file."""
        t = config if config is not None else yaml.safe_load(path.read_text())
        self.nodes = sorted([s["id"] for s in t["services"]] + [d["id"] for d in t["datastores"]])
        self.calls = [c for c in t["calls"] if c["cap"] > 0]            # client → server; failure flows server → client
        incoming: dict[str, float] = {}
        for c in t["calls"]:
            incoming[c["server"]] = incoming.get(c["server"], 0.0) + c["rps"]
        self.share = {(c["server"], c["client"]): min(1.0, c["rps"] / incoming.get(c["client"], c["rps"]))
                      for c in self.calls}
        self.any = {n: self._closure(n, lambda c: True) for n in self.nodes}
        self.sync = {n: self._closure(n, lambda c: c["cap"] >= 1.0) for n in self.nodes}

    def _closure(self, start: str, ok) -> set[str]:
        """Components a failure at `start` can reach (fixpoint over the config's call list)."""
        reach: set[str] = set()
        grew = True
        while grew:
            grew = False
            for c in self.calls:
                if ok(c) and (c["server"] == start or c["server"] in reach) and c["client"] not in reach | {start}:
                    reach.add(c["client"])
                    grew = True
        return reach

    def symptoms_of(self, x: str) -> list[str]:
        """Where a fault at x is clearly visible: x itself, or a synchronous direct client with call share ≥ 0.4."""
        return [x] + sorted(c["client"] for c in self.calls if c["server"] == x and c["cap"] >= 1.0
                            and self.share[(x, c["client"])] >= 0.4 and c["client"] in self.nodes)


def _pick(rnd: random.Random, xs: list[str]) -> str | None:
    return rnd.choice(sorted(xs)) if xs else None


def generate(plan: dict[str, int] = PLAN, seed: int = SEED) -> list[dict]:
    """Cases with their expected verdicts, decided here before any run."""
    topo, rnd = Topo(), random.Random(seed)
    # opaque ids from their own seeded stream (review round 5, minor 9): the product sees random case, change and alert
    # ids and one title template for causes and distractors alike, so no tie-break by id or title can favour the
    # cause; the case stream above is untouched, so the cases (and the grader's gbNNN ids) are the same as before
    ids_rnd = random.Random(seed ^ 0x0BAD1D5)

    def opaque(n: int = 8) -> str:
        return "".join(ids_rnd.choice("0123456789abcdef") for _ in range(n))

    roots = [n for n in topo.nodes if len(topo.symptoms_of(n)) > 0 and topo.any[n]]  # can fail visibly somewhere
    cases: list[dict] = []
    for cat, n in plan.items():
        made = tries = 0
        while made < n:
            tries += 1
            if tries > 5000:
                raise RuntimeError(f"gate bench: cannot generate {n} {cat} cases from the topology")
            c = rnd.choice(roots)
            t = rnd.choice(topo.symptoms_of(c))
            no_path = [d for d in topo.nodes if d not in (c, t) and t not in topo.any[d]]
            weak = [d for d in topo.nodes if d not in (c, t) and t in topo.any[d] and t not in topo.sync[d]
                    and d not in topo.any[c]]
            healthy_sync = [d for d in topo.nodes if d not in (c, t) and t in topo.sync[d] and d not in topo.any[c]]
            if cat == "G2":
                ds = sorted(set(rnd.sample(no_path, min(len(no_path), rnd.choice((1, 2))))))
                exp = {"outcome": "CONFIRMED", "eliminated": {d: "G2" for d in ds}} if ds else None
            elif cat == "G5":
                d = _pick(rnd, weak)
                exp = {"outcome": "CONFIRMED", "eliminated": {d: "G5"}} if d else None
            elif cat == "origin":
                d = _pick(rnd, healthy_sync)
                exp = {"outcome": "CONFIRMED", "eliminated": {d: "origin"}} if d else None
            elif cat == "abstain":
                benign = [d for d in topo.nodes if d not in (c, t) and d not in topo.any[c]]
                ds = sorted(set(rnd.sample(benign, rnd.choice((0, 1, 2)))))
                exp = {"outcome": "NOT_CONFIDENT", "eliminated": {}, "distractors": ds}
            else:  # control
                ds = sorted(set(rnd.sample(topo.nodes, rnd.choice((1, 2)))))
                exp = {"outcome": "NO_INCIDENT", "eliminated": {}, "distractors": ds}
            if exp is None:
                continue
            made += 1
            cid = f"gb{len(cases) + 1:03d}"                      # grader-side id only (never given to the product)
            sid = f"C{opaque(6)}"                                  # the scenario id the product sees
            dists = sorted(exp.get("distractors") or exp["eliminated"])
            inject = [{"change": f"D-{opaque()}", "target": d, "kind": "deploy", "at": "-3m", "title": f"{d}: change"}
                      for d in dists]
            effects = []
            cause = None
            if cat in ("G2", "G5", "origin"):
                cause = f"D-{opaque()}"
                inject.insert(0, {"change": cause, "target": c, "kind": "deploy", "at": "-3m", "title": f"{c}: change"})
                effects = [{"target": c, "error_rate": round(rnd.uniform(0.25, 0.6), 3), "from": "-2m", "change": cause}]
            elif cat == "abstain":
                effects = [{"target": c, "error_rate": round(rnd.uniform(0.25, 0.6), 3), "from": "-2m"}]
            spec = {"id": sid, "name": f"generated incident {sid.lower()}", "tenant": "acme", "onset": "anchor+3h",  # neutral
                    "inject": inject, "effects": effects, "seed": rnd.randrange(1, 10_000),
                    "alerts": [{"id": f"al-{opaque()}", "target": t, "metric": "error_rate", "at": "0m"}],
                    "report": BENCH_REPORT.format(target=t), "window_min": 30}
            ids = {x["target"]: x["change"] for x in inject}
            cases.append({"id": cid, "category": cat, "spec": spec, "symptom": t, "origin": c if cat != "control" else None,
                          "expected": {"outcome": exp["outcome"], "cause": cause,
                                       "eliminated": {ids[d]: EXPECT_REASON[r] for d, r in exp["eliminated"].items()}}})
    return cases


# ------------------------------------------------------------------ run + grade
def run_case(case: dict) -> dict:
    t0 = time.perf_counter()
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    try:
        res = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                             symptoms=p.symptoms, investigator=BaselineInvestigator(), graph=p.graph,
                                             run_id=p.run_id, window_min=p.scenario.get("window_min")))
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    blamed = res.cause_id if res.outcome == "CONFIRMED" else None
    got = {"outcome": res.outcome, "cause": blamed, "confident": res.confident, "error": res.error,
           "inferred": (res.inferred or {}).get("id"),
           # a change the gate ACCEPTED without confidence (outcome NOT_CONFIDENT): an abstention by outcome, but not a
           # true one (a bystander was accepted); reported separately, the verdict grading is unchanged
           "accepted_not_confident": res.cause_id if res.outcome == "NOT_CONFIDENT" else None,
           "sweep": {v["change"]: f"{v['status']}: {v['reason']}" for v in res.sweep}}
    return {**case, "got": got, **grade(case["expected"], got), "seconds": round(time.perf_counter() - t0, 2)}


ABSTAIN_OK = ("NOT_CONFIDENT", "UNKNOWN_ESCALATED")  # no change blamed, handed to a human (harness abstention_correct)


def grade(exp: dict, got: dict) -> dict:
    why = []
    if exp["outcome"] == "NOT_CONFIDENT":
        if got["outcome"] not in ABSTAIN_OK:
            why.append(f"outcome {got['outcome']} (expected an abstention: {' or '.join(ABSTAIN_OK)})")
    elif got["outcome"] != exp["outcome"]:
        why.append(f"outcome {got['outcome']} (expected {exp['outcome']})")
    if got["cause"] != exp["cause"]:
        why.append(f"blamed {got['cause']} (expected {exp['cause']})")
    if exp["outcome"] == "CONFIRMED":
        for d, gate in exp["eliminated"].items():
            v = got["sweep"].get(d, "absent")
            if not v.startswith(f"eliminated: {gate}"):
                why.append(f"{d}: {v[:120]} (expected eliminated by {gate})")
    return {"correct": not why, "why": why}


def eliminated_by(sweep: dict[str, str]) -> dict[str, str]:
    """{change: the gate that eliminated it} from a graded sweep ({change: "eliminated: G5: max flow …"})."""
    return {c: v.split(": ", 1)[1].split(":")[0].strip() for c, v in sweep.items() if v.startswith("eliminated: ")}


def detail(exp: dict, outcome: str, blamed: str | None, sweep: dict[str, str]) -> dict:
    """Per-case fields beyond the strict grade: was the expected cause blamed, and which gate eliminated each decoy."""
    elim = eliminated_by(sweep)
    return {"right_cause": exp["outcome"] == "CONFIRMED" and blamed == exp["cause"],
            "decoys_by": {d: elim.get(d, sweep.get(d, "absent").split(":")[0]) for d in exp.get("eliminated", {})}}


def buckets(rows: list[dict], cases: list[dict]) -> dict:
    """Where the cases went, beyond the strict grade (each case in exactly one of: correct, right cause with a decoy
    eliminated by another gate than the bench expects, abstained, wrong-confident, other), plus which gate
    eliminated the expected decoys."""
    exp = {c["id"]: c["expected"] for c in cases}
    out = {"correct": 0, "right_cause_other_gate": 0, "abstained_not_correct": 0, "wrong_confident": 0, "other": 0}
    by: dict[str, int] = {}
    for r in rows:
        if r["correct"]:
            out["correct"] += 1
        elif r["wrong_confident"]:
            out["wrong_confident"] += 1
        elif r["right_cause"]:
            out["right_cause_other_gate"] += 1
        elif r["abstained"]:
            out["abstained_not_correct"] += 1
        else:
            out["other"] += 1
            oo = out.setdefault("other_outcomes", {})
            k = f"{r.get('outcome')} (expected {exp[r['id']]['outcome']})"
            oo[k] = oo.get(k, 0) + 1
        for g in r["decoys_by"].values():
            by[g] = by.get(g, 0) + 1
    out["right_cause"] = sum(r["right_cause"] for r in rows)
    out["confirm_cases"] = sum(1 for r in rows if exp[r["id"]]["outcome"] == "CONFIRMED")
    out["decoys_eliminated_by"] = dict(sorted(by.items()))
    return out


def abstention_split(abst: list[dict]) -> dict:
    """Correct abstentions split by kind: a TRUE abstention (no change accepted: escalated, or the origin inferred)
    vs a bystander change the gate accepted but not confidently (correct by outcome, reported apart)."""
    return {"abstain_true": sum(1 for r in abst if r["correct"] and not r["got"].get("accepted_not_confident")),
            "abstain_bystander_not_confident": sum(1 for r in abst if r["correct"] and r["got"].get("accepted_not_confident"))}


def select(cases: list[dict], per_category: dict[str, int]) -> list[dict]:
    """The fast variant: the first n cases of each category of the full generated set (same ids, same cases)."""
    out = []
    for cat, n in per_category.items():
        out += [c for c in cases if c["category"] == cat][:n]
    return sorted(out, key=lambda c: c["id"])


def run(plan: dict[str, int] = PLAN, seed: int = SEED, progress: bool = False, fast: bool = False) -> dict:
    t0 = time.perf_counter()
    cases = generate(plan, seed)
    if fast:
        cases = select(cases, FAST)
        plan = FAST
    rows = []
    for c in cases:
        r = run_case(c)
        rows.append(r)
        if progress:
            print(f"{r['id']} {r['category']:8s} {'ok ' if r['correct'] else 'BAD'} {r['got']['outcome']:14s} "
                  f"{'; '.join(r['why'])[:160]}", flush=True)
    cats = {}
    for cat in plan:
        rs = [r for r in rows if r["category"] == cat]
        cats[cat] = {"cases": len(rs), "correct": sum(r["correct"] for r in rs)}
    abst = [r for r in rows if r["category"] == "abstain"]
    return {"seed": seed, "variant": "fast" if fast else "full", "cases": len(rows), "correct": sum(r["correct"] for r in rows),
            "by_category": cats,
            "abstain_inferred_origin": sum(1 for r in abst if r["got"]["inferred"] == r["origin"]),
            **abstention_split(abst),
            "seconds": round(time.perf_counter() - t0, 1),
            "failures": [{k: r[k] for k in ("id", "category", "symptom", "origin", "expected", "why")}
                         | {"got": {k: r["got"][k] for k in ("outcome", "cause", "confident", "error", "sweep")}}
                         for r in rows if not r["correct"]],
            "cases_detail": [{"id": r["id"], "category": r["category"], "symptom": r["symptom"], "origin": r["origin"],
                              "changes": [x["change"] + "@" + x["target"] for x in r["spec"]["inject"]],
                              "expected": r["expected"], "outcome": r["got"]["outcome"], "cause": r["got"]["cause"],
                              "accepted_not_confident": r["got"]["accepted_not_confident"],
                              "correct": r["correct"]} for r in rows]}


def blame_role(case_detail: dict) -> str | None:
    """What the blamed change WAS (the true cause, a distractor, or nothing): comparable across bench versions whose
    change ids differ (gbNNN-derived ids before round 5, opaque ids after)."""
    blamed = case_detail.get("cause")
    if blamed is None:
        return None
    return "cause" if blamed == (case_detail.get("expected") or {}).get("cause") else "distractor"


def recorded(path: str | None = None) -> tuple[str, dict] | None:
    """The newest recorded full bench: a harness run (checks.gate_bench) or evals/results/gate_bench.json."""
    res = ROOT / "evals" / "results"
    cands = [Path(path)] if path else sorted(res.glob("run_*.json"), reverse=True) + [res / "gate_bench.json"]
    for p in cands:
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        gb = (d.get("checks") or {}).get("gate_bench") if "checks" in d else d
        if gb and gb.get("cases_detail"):
            return p.name, {c["id"]: c for c in gb["cases_detail"]}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="20 of the 100 cases (the first 4 per category), for judge-check")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=None, help="write the JSON result here (default: print the summary only)")
    ap.add_argument("--check-recorded", nargs="?", const="", default=None,
                    help="pass iff every case reproduces the newest recorded full bench (or the given file)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    out = run(PLAN, a.seed, progress=not a.quiet, fast=a.fast)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    line = (f"gate verdicts {out['correct']}/{out['cases']} ("
            + ", ".join(f"{k} {v['correct']}/{v['cases']}" for k, v in out["by_category"].items()) + ")")
    if a.check_recorded is None:
        print(line)
        return 0 if out["correct"] == out["cases"] else 1
    rec = recorded(a.check_recorded or None)
    if rec is None:
        print(line + "; no recorded full bench to compare with (run make eval)")
        return 1
    name, cases = rec
    same = [c for c in out["cases_detail"] if c["id"] in cases
            and all(c[k] == cases[c["id"]][k] for k in ("correct", "outcome"))
            and blame_role(c) == blame_role(cases[c["id"]])]
    print(line + f"; {len(same)}/{out['cases']} reproduce {name}")
    return 0 if len(same) == out["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
