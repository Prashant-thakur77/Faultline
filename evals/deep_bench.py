"""Deep bench: multi-hop causes and downstream look-alikes (PREREGISTRATION amendment 2026-10-14).

The gate bench puts every cause 0–1 hops from its symptom and never puts a look-alike deploy downstream of the cause.
Here (same topology config, same oracle rule, same product path, a new seed):
  deep_onpath    cause → … → symptom over 2–4 visible hops, a look-alike deploy strictly between them (+ 0–1 no-path decoy)
  symptom_decoy  cause 1–4 visible hops upstream, a look-alike deploy on the alerting component itself (+ 0–1 no-path decoy)
  abstain_downstream  an UNCHANGED component degrades 1–4 visible hops upstream; 1–2 look-alike deploys downstream of it
                 (between it and the alerting component, or on it) → abstain (addendum 1: the adversarial test of G4 upstream)
Visible hop = a synchronous call (cap 1.0) with call share ≥ 0.4, followed server → client (the bench's own rule).
Expected: CONFIRMED, the upstream cause blamed, every decoy eliminated (look-alikes by G4: origin or upstream-explained,
no-path decoys by G2;
the gate that actually eliminated each decoy is reported). Arm T (telemetry only) runs on the same worlds.

    PYTHONPATH=backend uv run python evals/deep_bench.py [--out FILE]
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
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import gate_bench  # noqa: E402

SEED = 20261014        # development seed: its first run found the G4-upstream gap
FRESH_SEED = 20261016  # pre-registered confirmation seed (addendum 1), never looked at before the fix
PLAN = {"deep_onpath": 20, "symptom_decoy": 20, "abstain_downstream": 20,
        "two_causes_chain": 20, "weak_link": 20, "late_upstream": 20, "noisy_upstream": 20}   # addendum 2: adversarial
ABSTAIN_FINE = {"weak_link", "late_upstream", "noisy_upstream"}   # the expected cause, or an abstention


def visible_dist(topo: gate_bench.Topo) -> dict[str, dict[str, int]]:
    """{x: {y: visible hops from x to y}} over the bench's visibility rule (grader oracle over the config file)."""
    nxt: dict[str, list[str]] = {}
    for c in topo.calls:
        if c["cap"] >= 1.0 and c["client"] in topo.nodes and topo.share[(c["server"], c["client"])] >= 0.4:
            nxt.setdefault(c["server"], []).append(c["client"])
    out = {}
    for r in topo.nodes:
        d, q = {r: 0}, [r]
        while q:
            x = q.pop(0)
            for y in sorted(nxt.get(x, [])):
                if y not in d:
                    d[y] = d[x] + 1
                    q.append(y)
        out[r] = d
    return out


def generate(plan: dict[str, int] = PLAN, seed: int = SEED) -> list[dict]:
    topo, rnd = gate_bench.Topo(), random.Random(seed)
    ids_rnd = random.Random(seed ^ 0x0BAD1D5)

    def opaque(n: int = 8) -> str:
        return "".join(ids_rnd.choice("0123456789abcdef") for _ in range(n))

    dist = visible_dist(topo)
    pairs = {cat: sorted((c, t, k) for c in topo.nodes for t, k in dist[c].items()
                         if (2 <= k <= 4 if cat == "deep_onpath" else 1 <= k <= 4)) for cat in plan}

    def between(c: str, t: str, k: str) -> list[str]:   # strictly between c and t on a visible chain
        return sorted(m for m, km in dist[c].items() if 0 < km < k and dist[m].get(t) == k - km)
    cases: list[dict] = []
    weak = sorted((u, s) for u in topo.nodes for s in topo.any[u] if s != u and s not in dist[u] and s in topo.nodes)
    for cat, n in plan.items():
        if cat in ("two_causes_chain", "weak_link", "late_upstream", "noisy_upstream"):
            for _ in range(n):
                cases.append(_adversarial(cat, rnd, opaque, pairs["symptom_decoy"], weak, len(cases)))
            continue
        for _ in range(n):
            c, t, k = rnd.choice(pairs[cat])
            if cat == "deep_onpath":
                looks = [rnd.choice(between(c, t, k))]
            elif cat == "symptom_decoy":
                looks = [t]
            else:   # abstain_downstream: 1–2 look-alikes downstream of the unchanged origin, on the chain or the symptom
                pool = between(c, t, k) + [t]
                looks = sorted(set(rnd.sample(pool, min(len(pool), rnd.choice((1, 2))))))
            decoys = {look: "G4" for look in looks}   # the G4 family: origin (in band) or upstream-explained
            no_path = sorted(d for d in topo.nodes if d not in (c, t, *looks) and t not in topo.any[d])
            if cat != "abstain_downstream" and no_path and rnd.random() < 0.5:
                decoys[rnd.choice(no_path)] = "G2"
            cause = f"D-{opaque()}" if cat != "abstain_downstream" else None
            inject = [{"change": cause, "target": c, "kind": "deploy", "at": "-3m", "title": f"{c}: change"}] if cause else []
            inject += [{"change": f"D-{opaque()}", "target": d, "kind": "deploy", "at": "-3m", "title": f"{d}: change"}
                       for d in sorted(decoys)]
            look = looks[0]
            rnd.shuffle(inject)          # the cause's position in the change list carries no signal
            sid = f"C{opaque(6)}"
            spec = {"id": sid, "name": f"generated incident {sid.lower()}", "tenant": "acme", "onset": "anchor+3h",
                    "inject": inject,
                    "effects": [{"target": c, "error_rate": round(rnd.uniform(0.25, 0.6), 3), "from": "-2m",
                                 **({"change": cause} if cause else {})}],
                    "seed": rnd.randrange(1, 10_000),
                    "alerts": [{"id": f"al-{opaque()}", "target": t, "metric": "error_rate", "at": "0m"}],
                    "report": gate_bench.BENCH_REPORT.format(target=t), "window_min": 30}
            ids = {x["target"]: x["change"] for x in inject}
            cases.append({"id": f"db{len(cases) + 1:03d}", "category": cat, "spec": spec, "symptom": t, "origin": c,
                          "hops": k, "lookalike": look,
                          "expected": {"outcome": "CONFIRMED", "cause": cause,
                                       "eliminated": {ids[d]: g for d, g in decoys.items()}} if cause else
                                      {"outcome": "NOT_CONFIDENT", "cause": None, "eliminated": {}}})
    return cases


def _adversarial(cat: str, rnd: random.Random, opaque, visible: list[tuple], weak: list[tuple], n: int) -> dict:
    """Addendum 2: two faults (or a late / unchanged / weakly linked upstream fault) around the alerting component s.
    u is upstream of s; the alert is on s; every fault is a real effect of its own."""
    if cat == "weak_link":
        u, s = rnd.choice(weak)
        k = None
    else:
        u, s, k = rnd.choice(visible)
    cu, cs = f"D-{opaque()}", f"D-{opaque()}"
    inject = [{"change": cs, "target": s, "kind": "deploy", "at": "-3m", "title": f"{s}: change"}]
    if cat != "noisy_upstream":   # u carries a change except in noisy_upstream
        inject.append({"change": cu, "target": u, "kind": "deploy", "at": "-3m", "title": f"{u}: change"})
    rnd.shuffle(inject)
    s_val = round(rnd.uniform(0.10, 0.30) if cat == "two_causes_chain" else rnd.uniform(0.25, 0.6), 3)
    u_val = round(rnd.uniform(0.25, 0.6), 3)
    effects = [{"target": s, "error_rate": s_val, "from": "-2m", "change": cs},
               {"target": u, "error_rate": u_val, "from": "0m" if cat == "late_upstream" else "-2m",
                **({"change": cu} if cat != "noisy_upstream" else {})}]
    sid = f"C{opaque(6)}"
    spec = {"id": sid, "name": f"generated incident {sid.lower()}", "tenant": "acme", "onset": "anchor+3h",
            "inject": inject, "effects": effects, "seed": rnd.randrange(1, 10_000),
            "alerts": [{"id": f"al-{opaque()}", "target": s, "metric": "error_rate", "at": "0m"}],
            "report": gate_bench.BENCH_REPORT.format(target=s), "window_min": 30}
    exp = ({"outcome": "NOT_CONFIDENT", "cause": None, "eliminated": {}} if cat == "two_causes_chain" else
           {"outcome": "CONFIRMED", "cause": cs, "eliminated": {}})
    return {"id": f"db{n + 1:03d}", "category": cat, "spec": spec, "symptom": s, "origin": s, "hops": k,
            "lookalike": u, "expected": exp}


def run(seed: int = SEED, progress: bool = True) -> dict:
    import mismatch_eval

    t0 = time.perf_counter()
    cases = generate(seed=seed)
    rows = []
    for c in cases:
        r = gate_bench.run_case(c)
        g = r["got"]
        blamed = g["cause"]
        row = {"id": c["id"], "category": c["category"], "hops": c["hops"], "outcome": g["outcome"], "blamed": blamed,
               "correct": r["correct"], "why": r["why"],
               "wrong_confident": blamed is not None and blamed != c["expected"]["cause"],   # any blame in abstain worlds
               "abstained": blamed is None and g["outcome"] in gate_bench.ABSTAIN_OK,
               "ok": (blamed is None and g["outcome"] in gate_bench.ABSTAIN_OK) if c["expected"]["cause"] is None else
                     (blamed == c["expected"]["cause"] or (c["category"] in ABSTAIN_FINE and blamed is None
                                                          and g["outcome"] in gate_bench.ABSTAIN_OK)),
               **gate_bench.detail(c["expected"], g["outcome"], blamed, g["sweep"]),
               "arm_t": mismatch_eval.arm_t_case(c)["score"]}
        rows.append(row)
        if progress:
            print(f"[deep] {c['id']} {c['category']} hops={c['hops']}: {g['outcome']} right={row['right_cause']} "
                  f"T={row['arm_t']}", file=sys.stderr, flush=True)

    def summ(rs: list[dict]) -> dict:
        return {"cases": len(rs), "ok": sum(r["ok"] for r in rs), "right_cause": sum(r["right_cause"] for r in rs),
                "correct": sum(r["correct"] for r in rs),
                "wrong_confident": sum(r["wrong_confident"] for r in rs), "abstained": sum(r["abstained"] for r in rs),
                "arm_t": round(sum(r["arm_t"] for r in rs), 2)}

    out = {"seed": seed, "all": summ(rows) | {"buckets": gate_bench.buckets(rows, cases)},
           "by_category": {cat: summ([r for r in rows if r["category"] == cat]) for cat in PLAN},
           "by_hops": {str(h): summ([r for r in rows if r["hops"] == h])
                       for h in sorted({r["hops"] for r in rows if r["hops"] is not None})},
           "misses": [{k: r[k] for k in ("id", "category", "hops", "outcome", "blamed", "decoys_by")}
                      for r in rows if not r["correct"]],
           "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    r = run(seed=a.seed)
    print(json.dumps({k: r[k] for k in ("all", "by_category", "by_hops", "misses")}, indent=1, default=str))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
