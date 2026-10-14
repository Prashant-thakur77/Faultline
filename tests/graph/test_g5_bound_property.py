"""Property: the G5 sufficiency bound holds in the simulated world (docs/EXPLAINER.md "why is the max-flow test
valid?", docs/design/scenario_numbers.md §1 proof sketch).

On random small DAGs written to scratch FalkorDB graphs (fan-in, fan-out, reconvergent paths, criticality caps 1.0 /
0.02 plus intermediate ones, random call shares), one fault is injected at a time. The telemetry SIMULATOR
(`sim/telemetry.py`, the world the agent observes) propagates it, and its empirical share at every other node is
compared with the max flow the GATE computes (`Gate.flow` → Q-GATE-3 → `algo.maxFlow`, name from the registry).

Empirical share of the fault at t = (err_fault(t) − err_nofault(t)) / (1 − err_nofault(t)) in the worst of 3 minutes,
both runs with the same seed (identical noise). That is what the fault adds, with the baseline removed, the same
correction the gate applies to the observed share.

What is asserted, and why this is the honest form of the claim:
  * no path ⇒ zero share (G2 is sound);
  * multiplicity 1 (every node on an s→t path has a single path to t): share ≤ maxFlow. This is the bound
    EXPLAINER states, and the case every G5 elimination in the scenarios is in (last test);
  * any DAG: share ≤ min(1, k · maxFlow), k = the largest number of distinct PROPAGATES_TO paths from a node on an
    s→t path to t. A request to t that reaches the cut edge along k distinct call paths gets k chances to fail
    (the design note's `k_max`). The plain bound can FAIL when k > 1; `test_reconvergent_paths_break_the_plain_bound`
    pins a counterexample so this limit stays visible.
Cases are drawn from a fixed seed list and are not filtered: every generated (source, target) pair is checked.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path

import pytest

from faultline.mcp_server import context
from faultline.mcp_server import tools as T
import yaml

from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.ro import RO
from faultline.sim.telemetry import MINUTE, Effect, simulate

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
CAPS = (1.0, 1.0, 0.02, 0.3, 0.6)  # criticality (sync / best-effort) plus intermediate values: a stronger test
SHARES = (0.25, 0.5, 1.0, 1.0)     # calls per incoming request a client makes to a server (min(1, ·) in the sim)
TOL = 1e-4                         # the simulator rounds windows to 5 decimals
SEEDS = list(range(40))
PATHS = "MATCH p = (w:Node)-[:PROPAGATES_TO*1..8]->(t:Node {id:$t}) RETURN w.id AS w, count(p) AS n"
ON_PATH = ("MATCH p = (s:Node {id:$s})-[:PROPAGATES_TO*1..8]->(t:Node {id:$t}) UNWIND nodes(p) AS w "
           "RETURN DISTINCT w.id AS w")


def _dag(rnd: random.Random) -> tuple[list[str], list[tuple[str, str, float]], dict[tuple[str, str], float]]:
    """Failure flows from lower to higher index (server n_i → client n_j). Traffic: 100 rps of entry load into every
    node, and each client calls each of its servers with rps = share × its own incoming rps (clients first)."""
    n = rnd.randint(4, 7)
    nodes = [f"n{i}" for i in range(n)]
    edges = [(nodes[i], nodes[j], rnd.choice(CAPS)) for j in range(1, n) for i in range(j) if rnd.random() < 0.5]
    incoming = {x: 100.0 for x in nodes}
    calls: dict[tuple[str, str], float] = {}
    for v in reversed(nodes):
        for u, w, _ in edges:
            if w == v:
                r = round(rnd.choice(SHARES) * incoming[v], 3)
                calls[(v, u)] = r
                incoming[u] += r
    return nodes, edges, calls


def _write(g, nodes, edges, calls) -> None:
    writes.upsert_nodes(g, "Service", [{"id": x} for x in nodes + ["lg"]])
    writes.upsert_edges(g, "CALLS", "Service", "Service",
                        [{"src": c, "dst": s, "props": {"rps": r}} for (c, s), r in calls.items()]
                        + [{"src": "lg", "dst": x, "props": {"rps": 100.0}} for x in nodes])
    if edges:
        writes.upsert_edges(g, "PROPAGATES_TO", "Service", "Service",
                            [{"src": u, "dst": v, "props": {"cap": c}} for u, v, c in edges])


def _windows(ro: RO, target: str, start: int) -> list[float]:
    return [r["value"] for r in ro.run("Q-MW-1", {"target": target, "metric": "error_rate", "since": start,
                                                 "until": start + 2 * MINUTE}).rows]


def _multiplicity(g, s: str, t: str) -> int:
    counts = {r[0]: int(r[1]) for r in g.ro_query(PATHS, {"t": t}).result_set}
    on_path = [r[0] for r in g.ro_query(ON_PATH, {"s": s, "t": t}).result_set]
    return max([1] + [counts.get(w, 1) for w in on_path if w not in (s, t)])


@pytest.fixture
def scratch_room():
    db = gclient.engine()
    names: list[str] = []

    def make():
        name = f"scratch_acme_g5prop_{uuid.uuid4().hex[:10]}"
        names.append(name)
        return name, db.select_graph(name)

    yield make
    for n in names:
        gcopy.delete_if_exists(db, n)


def _measure(name, g, nodes, edges, calls, seed: int, fault: float):
    """[(source, target, empirical share, plain max flow, multiplicity, the gate's G5 bound)] for every ordered pair."""
    _write(g, nodes, edges, calls)
    ro = RO("acme", name)
    simulated = sorted({u for u, _, _ in edges} | {v for _, v, _ in edges})  # the simulator models nodes with edges
    simulate(g, ro, onset_ms=0, effects=[], seed=seed, start_ms=0, minutes=3)
    out = []
    for i, s in enumerate(simulated):
        start = (10 + 10 * i) * MINUTE
        simulate(g, ro, onset_ms=0, effects=[Effect(s, fault, start)], seed=seed, start_ms=start, minutes=3)
        for t in simulated:
            if t == s:
                continue
            base, hit = _windows(ro, t, 0), _windows(ro, t, start)
            assert len(base) == len(hit) == 3, (t, base, hit)
            share = max((y - x) / (1 - x) for x, y in zip(base, hit))
            rows = ro.run("Q-GATE-3", {"sources": [s], "symptom": t}).rows
            raw = float(rows[0]["max_flow"]) if rows else 0.0
            tok = context.bind("acme", graph=name)
            try:  # the suspect's own G5 bound, exactly as the gate's sweep and confirm compute it
                bound = T.impact_bound(suspect_ids=[s], symptom_id=t, observed_share=0.5)["flow_share"]
            finally:
                context.unbind(tok)
            out.append((s, t, share, raw, _multiplicity(g, s, t), bound))
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_maxflow_bounds_the_simulated_share(scratch_room, seed):
    rnd = random.Random(seed)
    nodes, edges, calls = _dag(rnd)
    if not edges:
        pytest.skip("generated DAG has no edges")  # reported as a skip, never silently dropped
    name, g = scratch_room()
    rows = _measure(name, g, nodes, edges, calls, seed, fault=rnd.uniform(0.2, 0.95))
    for s, t, share, flow, k, bound in rows:
        if flow == 0.0:
            assert share <= TOL, f"seed {seed}: {s}→{t} has no path (max flow 0) but share {share:.5f}"
        if k == 1:
            assert share <= flow + TOL, f"seed {seed}: {s}→{t} share {share:.5f} > max flow {flow:.5f} (k=1)"
        assert share <= min(1.0, k * flow) + TOL, f"seed {seed}: {s}→{t} share {share:.5f} > {k} × {flow:.5f}"
        assert share <= bound + TOL, f"seed {seed}: {s}→{t} share {share:.5f} > the gate's G5 bound {bound:.5f}"


def test_reconvergent_paths_break_the_plain_bound(scratch_room):
    """Documented limit: s →(0.3) a, then a fans out to b and c, which both feed t. A request to t calls b and c, each
    calls a, each a-request calls s: two independent chances to fail through the single cut edge s→a. The share at t
    exceeds maxFlow = 0.3 and stays within k · maxFlow with k = 2."""
    name, g = scratch_room()
    nodes = ["s", "a", "b", "c", "t"]
    edges = [("s", "a", 0.3), ("a", "b", 1.0), ("a", "c", 1.0), ("b", "t", 1.0), ("c", "t", 1.0)]
    # every client calls its servers once per incoming request (share 1.0): t gets 100 → b, c get 100 each → a gets 200
    calls = {("t", "b"): 100.0, ("t", "c"): 100.0, ("b", "a"): 200.0, ("c", "a"): 200.0, ("a", "s"): 500.0}
    rows = {(s, t): (share, flow, k, b) for s, t, share, flow, k, b in _measure(name, g, nodes, edges, calls, 7, fault=0.9)}
    share, flow, k, bound = rows[("s", "t")]
    assert flow == pytest.approx(0.3) and k == 2
    assert share > flow + 0.05, f"expected the plain bound to fail here (share {share:.4f}, max flow {flow})"
    assert share <= k * flow + TOL
    assert bound == pytest.approx(min(1.0, k * flow)) and share <= bound + TOL   # the gate now uses the sound bound


def test_scenario_g5_eliminations_have_multiplicity_one():
    """Every distractor a scenario expects G5 to reject sits on a single path to its symptom, so its elimination
    rests on the k = 1 bound (the sound case). Reads the golden graph read-only and the grader-only truth files."""
    db = gclient.engine()
    if not gcopy.exists(db, "golden_acme"):
        pytest.skip("golden_acme not seeded")
    g = db.select_graph("golden_acme")
    scen = {s["id"]: s for s in yaml.safe_load((ROOT / "data/scenarios/scenarios.yaml").read_text())}
    checked = 0
    cases = []
    for path in sorted((ROOT / "data/scenarios").glob("*.truth.json")):
        t = json.loads(path.read_text())
        # multi-incident scenarios (S14 alert storm) grade each incident with its own primary symptom and distractors
        cases += [{**i, "scenario": t["scenario"]} for i in t["incidents"]] if t.get("incidents") else [t]
    for t in cases:
        d = t.get("distractors") or {}
        g5 = [c for c, gate in d.items() if gate == "G5"] if isinstance(d, dict) else \
            (list(d) if t.get("distractor_rejected_by") == "G5" else [])
        for change in g5:
            target = next(x["target"] for x in scen[t["scenario"]]["inject"] if x["change"] == change)
            k = _multiplicity(g, target, t["symptom"])
            assert k == 1, f"{t['scenario']} {change}: multiplicity {k} → the plain max-flow bound is not guaranteed"
            checked += 1
    assert checked >= 3  # S1 (email → checkout), S2 (FX feed → revenue KPI), S14 (fraud-detection → queue → checkout)


def _transfer(g, s: str, t: str) -> float:
    """Q-VERIFY-ALLOW's per-origin transfer, path by path: Σ over s → t paths (≤ 8 hops) of the product of the caps."""
    total = 0.0
    for (caps,) in g.ro_query("MATCH p = (s:Node {id:$s})-[:PROPAGATES_TO*1..8]->(t:Node {id:$t}) "
                              "RETURN [r IN relationships(p) | r.cap]", {"s": s, "t": t}).result_set:
        prod = 1.0
        for c in caps:
            prod *= c
        total += prod
    return total


@pytest.mark.parametrize("seed", SEEDS[:15])
def test_path_transfer_bounds_what_one_origin_adds_downstream(scratch_room, seed):
    """The verification allowance's model (Q-VERIFY-ALLOW, review M1): what a fault at s adds to t's error rate, in
    every minute, is at most the path transfer (Σ over paths of the product of caps) × what it adds at s. The bound
    holds where the bottleneck max flow does not (multi-hop caps multiply in the simulator). Same random DAGs and
    seeds as above; every (s, t) pair is checked."""
    rnd = random.Random(seed)
    nodes, edges, calls = _dag(rnd)
    if not edges:
        pytest.skip("generated DAG has no edges")
    name, g = scratch_room()
    _write(g, nodes, edges, calls)
    ro = RO("acme", name)
    simulated = sorted({u for u, _, _ in edges} | {v for _, v, _ in edges})
    fault = rnd.uniform(0.2, 0.95)
    simulate(g, ro, onset_ms=0, effects=[], seed=seed, start_ms=0, minutes=3)
    for i, s in enumerate(simulated):
        start = (10 + 10 * i) * MINUTE
        simulate(g, ro, onset_ms=0, effects=[Effect(s, fault, start)], seed=seed, start_ms=start, minutes=3)
        added_s = max(y - x for x, y in zip(_windows(ro, s, 0), _windows(ro, s, start)))
        for t in simulated:
            if t == s:
                continue
            added_t = [y - x for x, y in zip(_windows(ro, t, 0), _windows(ro, t, start))]
            w = _transfer(g, s, t)
            assert max(added_t) <= w * added_s + TOL, f"seed {seed}: {s}→{t} adds {max(added_t):.5f} > {w:.4f} × {added_s:.5f}"
