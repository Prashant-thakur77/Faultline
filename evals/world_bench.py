"""Independent-parameter world bench (PREREGISTRATION amendment 2026-10-16 and its acme addendum).

Not blind: written by the agent that audited the gate. What differs from the gate bench and the deep bench is HOW worlds
are drawn: by a world rule, not by gate category.
  cause      (60 %) one changed component with a fault U(0.05, 0.6); expected CONFIRMED with that change
  unchanged  (25 %) a fault U(0.05, 0.6) on a component with NO change; expected an abstention
  quiet      (15 %) no fault; expected NO_INCIDENT
Every world gets 1–3 benign deploys on components drawn uniformly (any position: upstream, downstream or unrelated, so
look-alikes downstream of the fault happen by chance). The cause deploys at a uniform minute in [−15, −3]; faults start
at −2m. The alert is on a component the fault visibly reaches: error ≥ 0.05 under the simulator's propagation rule
(cap × call share along the best single path, ≤ 4 hops, the faulty component itself included), computed here from the
topology config. Arms T and T+ run on the same worlds.

--tenant globex (addendum 2026-10-16, item 3): the same world rule on the 200-service globex tenant. Its oracle is
built from the globex topology generator (seed 42, the config the seeder writes) and must equal the engine's simulator
view of golden_globex (every failure edge, cap and call share) before any world runs; the simulator reads that view
page by page (Q-SIM-2), so globex's 305 failure edges no longer exceed one read.

    PYTHONPATH=backend scripts/memguard.sh 4000 uv run python evals/world_bench.py --reason "…"
    PYTHONPATH=backend scripts/memguard.sh 4000 uv run python evals/world_bench.py --tenant globex --n 200 --reason "…"
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

SEED = 20261131
N_WORLDS = 100
VISIBLE = 0.05
OUT = ROOT / "evals" / "results" / "world_bench.json"
OUT_BY_TENANT = {"acme": OUT, "globex": ROOT / "evals" / "results" / "world_bench_globex.json"}
TENANTS = ("acme", "globex")


def globex_config() -> dict:
    """globex's topology in the config-file shape the oracle reads, from the deterministic generator the seeder uses
    (seed 42): the system under observation, never the engine."""
    from faultline.ingest.globex import topology

    t = topology.generate(42)
    return {"services": [{"id": x["id"]} for x in t.services], "datastores": [{"id": x["id"]} for x in t.datastores],
            "calls": [{"client": c.client, "server": c.server, "rps": c.rps, "cap": c.cap} for c in t.calls]}


def topo_for(tenant: str) -> gate_bench.Topo:
    if tenant == "acme":
        return gate_bench.Topo()
    if tenant == "globex":
        return gate_bench.Topo(config=globex_config())
    raise ValueError(f"unknown tenant {tenant!r} (one of {', '.join(TENANTS)})")


def oracle_check(tenant: str) -> dict:
    """The oracle's failure edges (cap > 0 between services/datastores, call share as the simulator computes it) must
    equal the simulator's view of the tenant's golden graph, read through the RO wrapper. A mismatch means the grader
    and the world disagree: refuse to run."""
    from faultline.graph.ro import RO
    from faultline.graph.tenant import golden_graph
    from faultline.sim.telemetry import sim_view

    topo = topo_for(tenant)
    orc = {(c["server"], c["client"]): (float(c["cap"]), round(topo.share[(c["server"], c["client"])], 9))
           for c in topo.calls if c["server"] in topo.nodes and c["client"] in topo.nodes}
    view = sim_view(RO(tenant, golden_graph(tenant)))
    eng = {(r["src"], r["dst"]): (float(r["cap"]), round(min(1.0, float(r["rps"] or 0) / float(r["in_rps"] or 1)), 9))
           for r in view}
    diff = sorted(k for k in set(orc) | set(eng) if orc.get(k) != eng.get(k))
    return {"oracle_edges": len(orc), "engine_edges": len(eng), "equal": not diff, "differences": [list(k) for k in diff[:20]]}


def best_transfer(topo: gate_bench.Topo, src: str, max_hops: int = 4) -> dict[str, float]:
    """{node: best single-path product of cap × call share from src} over ≤ max_hops failure edges (server → client)."""
    best = {src: 1.0}
    frontier = {src: 1.0}
    for _ in range(max_hops):
        nxt: dict[str, float] = {}
        for u, w in frontier.items():
            for c in topo.calls:
                if c["server"] == u and c["client"] in topo.nodes:
                    x = w * c["cap"] * topo.share[(c["server"], c["client"])]
                    if x > best.get(c["client"], 0.0) and x > nxt.get(c["client"], 0.0):
                        nxt[c["client"]] = x
        best.update(nxt)
        frontier = nxt
    return best


def generate(n: int = N_WORLDS, seed: int = SEED, tenant: str = "acme") -> list[dict]:
    topo, rnd = topo_for(tenant), random.Random(seed)
    ids_rnd = random.Random(seed ^ 0x0BAD1D5)

    def opaque(k: int = 8) -> str:
        return "".join(ids_rnd.choice("0123456789abcdef") for _ in range(k))

    cases: list[dict] = []
    while len(cases) < n:
        u = rnd.random()
        kind = "cause" if u < 0.60 else ("unchanged" if u < 0.85 else "quiet")
        origin = rnd.choice(topo.nodes)
        err = round(rnd.uniform(0.05, 0.6), 3)
        if kind == "quiet":
            symptom = rnd.choice(topo.nodes)
        else:
            vis = sorted(v for v, x in best_transfer(topo, origin).items() if err * x >= VISIBLE)
            symptom = rnd.choice(vis)
        others = [x for x in topo.nodes if x != origin or kind == "quiet"]
        benign = sorted(set(rnd.sample(others, rnd.choice((1, 2, 3)))))
        inject = [{"change": f"D-{opaque()}", "target": d, "kind": "deploy", "at": f"-{rnd.randint(3, 15)}m",
                   "title": f"{d}: change"} for d in benign]
        cause = None
        if kind == "cause":
            cause = f"D-{opaque()}"
            inject.append({"change": cause, "target": origin, "kind": "deploy", "at": f"-{rnd.randint(3, 15)}m",
                           "title": f"{origin}: change"})
        rnd.shuffle(inject)
        effects = [] if kind == "quiet" else [{"target": origin, "error_rate": err, "from": "-2m",
                                               **({"change": cause} if cause else {})}]
        sid = f"C{opaque(6)}"
        spec = {"id": sid, "name": f"generated incident {sid.lower()}", "tenant": tenant, "onset": "anchor+3h",
                "inject": inject, "effects": effects, "seed": rnd.randrange(1, 10_000),
                "alerts": [{"id": f"al-{opaque()}", "target": symptom, "metric": "error_rate", "at": "0m"}],
                "report": gate_bench.BENCH_REPORT.format(target=symptom), "window_min": 30}
        exp = ({"outcome": "CONFIRMED", "cause": cause, "eliminated": {}} if kind == "cause" else
               {"outcome": "NOT_CONFIDENT", "cause": None, "eliminated": {}} if kind == "unchanged" else
               {"outcome": "NO_INCIDENT", "cause": None, "eliminated": {}})
        cases.append({"id": f"wb{len(cases) + 1:03d}", "category": kind, "spec": spec, "symptom": symptom,
                      "origin": origin if kind != "quiet" else None, "benign": benign, "error": err, "expected": exp})
    return cases


def run(progress: bool = True, n: int = N_WORLDS, seed: int = SEED, tenant: str = "acme") -> dict:
    import harness

    t0 = time.perf_counter()
    check = oracle_check(tenant) if tenant != "acme" else None
    if check is not None and not check["equal"]:
        raise SystemExit(f"world bench: the {tenant} oracle and the engine's simulator view differ: {check}")
    cases = generate(n=n, seed=seed, tenant=tenant)
    rows, log = [], []
    for i, c in enumerate(cases):
        r = gate_bench.run_case(c)
        g, exp = r["got"], c["expected"]
        blamed = g["cause"]
        tt = baselines.both(c)
        rows.append({"id": c["id"], "category": c["category"], "error": c["error"], "outcome": g["outcome"], "blamed": blamed,
                     "accepted_not_confident": g.get("accepted_not_confident"),
                     "right_cause": exp["outcome"] == "CONFIRMED" and blamed == exp["cause"],
                     "wrong_confident": blamed is not None and blamed != exp["cause"],
                     "abstained": blamed is None and g["outcome"] in gate_bench.ABSTAIN_OK,
                     "verdict_ok": (blamed == exp["cause"] and g["outcome"] == "CONFIRMED") if exp["outcome"] == "CONFIRMED"
                     else (blamed is None and (g["outcome"] in gate_bench.ABSTAIN_OK if exp["outcome"] == "NOT_CONFIDENT"
                                               else g["outcome"] == "NO_INCIDENT")),
                     "t": baselines.score(exp, tt["t"]), "tplus": baselines.score(exp, tt["tplus"]),
                     "tplus_outcome": tt["tplus"]["outcome"]})
        if progress:
            x = rows[-1]
            print(f"[world] {x['id']} {x['category']} err={x['error']}: {x['outcome']} right={x['right_cause']} "
                  f"wc={x['wrong_confident']} T+={x['tplus_outcome']}", file=sys.stderr, flush=True)
        if (i + 1) % (50 if tenant == "acme" else 25) == 0:
            harness._relieve_engine(f"world-{tenant}-{i + 1}" if tenant != "acme" else f"world-{i + 1}", log)

    def summ(rs: list[dict]) -> dict:
        cause = [r for r in rs if r["category"] == "cause"]
        out = {"cases": len(rs), "cause_cases": len(cause), "right_cause": sum(r["right_cause"] for r in rs),
               "wrong_confident": sum(r["wrong_confident"] for r in rs), "abstained": sum(r["abstained"] for r in rs),
               "verdict_ok": sum(r["verdict_ok"] for r in rs),
               "bystander_not_confident": sum(1 for r in rs if r["accepted_not_confident"])}
        for arm in ("t", "tplus"):
            out[arm] = {"right_strict": sum(r[arm]["right_strict"] for r in cause),
                        "right_frac": round(sum(r[arm]["right_frac"] for r in cause), 2),
                        "wrong_any": sum(1 for r in rs if r[arm]["wrong_frac"] > 0),
                        "wrong_frac": round(sum(r[arm]["wrong_frac"] for r in rs), 2),
                        "abstained": sum(r[arm]["abstained"] for r in rs)}
        return out

    return {"seed": seed, "tenant": tenant, "n": n, "oracle_check": check, "all": summ(rows),
            "by_category": {k: summ([r for r in rows if r["category"] == k]) for k in ("cause", "unchanged", "quiet")},
            "rows": rows, "engine_pressure": log, "seconds": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", required=True)
    ap.add_argument("--tenant", choices=TENANTS, default="acme")
    ap.add_argument("--n", type=int, default=N_WORLDS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=None, help="default: evals/results/world_bench[_globex].json")
    a = ap.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    r = run(n=a.n, seed=a.seed, tenant=a.tenant)
    r.update({"started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": a.reason})
    Path(a.out or OUT_BY_TENANT[a.tenant]).write_text(json.dumps(r, indent=1, default=str) + "\n")
    print(json.dumps({"all": r["all"], "by_category": r["by_category"]}, indent=1))


if __name__ == "__main__":
    main()
