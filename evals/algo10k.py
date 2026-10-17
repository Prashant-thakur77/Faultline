"""All 10 FalkorDB `algo.*` procedures at 10,000 services, against an eval-only NetworkX comparator (M20 Wave B).

Pre-registered in evals/PREREGISTRATION.md (addendum 2026-10-17, 21:10 IST). FalkorDB publishes algorithm speed
(PageRank 3.5x, WCC 6x against Neo4j); this measures the 10 procedures Faultline uses, on its own 10k-service scale
world, against NetworkX on the SAME extracted input, and checks that both give the same answers.

    make algo10k                                         # → evals/results/algo10k.json
    PYTHONPATH=backend uv run --group comparator python evals/algo10k.py --size 1k --services 200 \
        --runs 3 --out /tmp/a.json                       # a tiny smoke variant (one 200-service unit)

NetworkX is an OFFLINE COMPARATOR ONLY: it lives in evals/ (an optional `comparator` dependency group), never in
backend/faultline (scripts/lint_single_store.py bans it there), and nothing the product decides ever reads it.

Per workload (one per procedure, the call forms the product's templates use; sources and targets from the world
config via evals/scale.py's planted incident, never from results):
1. FalkorDB on the 10k product graph (`golden_scale10k`): R runs through GRAPH.RO_QUERY (TIMEOUT 10,000 ms, the
   engine's TIMEOUT_MAX; a timeout is reported as one), the engine's reported execution ms p50/p95/p99 and wall ms.
2. The workload's input extracted from FalkorDB (one read), built as a NetworkX graph; NetworkX timed over NX_RUNS
   runs (1 when one run takes over NX_SLOW_S), its graph bytes and its peak working bytes (tracemalloc, a separate
   run; skipped for computations over NX_SLOW_S).
3. The same answers, by the pre-registered criterion per procedure (labelPropagation: n/a, see CRITERIA).
4. Memory of the same graph: every workload's input together, written as a projection graph by the product's writers
   (engine used_memory delta, settled) against NetworkX's bytes for the same nodes and edges; the FalkorDB workloads
   are timed again on that projection (identical input to NetworkX) and must give the same answers there.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import re
import statistics
import sys
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

OUT = ROOT / "evals" / "results" / "algo10k.json"
R = 20
NX_RUNS = 5
NX_SLOW_S = 10.0
TIMEOUT_MS = 10_000
TOP = 10
REL_TOL = 1e-6
PAGE = 50_000
WCC_LABELS = ("Service", "Datastore", "Table", "KPI", "Dashboard")            # connectivity.cypher
LPA_LABELS = ("Incident", "Symptom", "Deploy", "Service", "Datastore", "Transform", "Table")   # families.cypher
LPA_RELS = ("HAS_SYMPTOM", "CAUSED", "CHANGED")
CENT_LABELS = ("Service", "Datastore")                                       # chokepoints.cypher
CRITERIA = {
    "bfs": "the same set of reached ids",
    "sppaths": "the same path weights in order, and the same paths where a weight is unique",
    "sspaths": "every target whose NetworkX distance (≤ 8 hops) is below the largest returned weight is returned at "
               "that distance",
    "pagerank": "the same top 10 in order",
    "betweenness": f"every score within {REL_TOL} relative",
    "harmonic": "the same top-10 set (FalkorDB's harmonic centrality is approximate; max relative error reported)",
    "wcc": "an identical partition",
    "cdlp": "n/a: NetworkX has no label propagation with the same update rule (community counts and time shown)",
    "maxflow": "the same value within 1e-9",
    "msf": "the same total weight and edge count (edge sets may differ on ties)",
}

# FalkorDB calls: `{algo:<key>}` placeholders resolved by graph/algo/registry.py, exactly as the templates do
CALLS = {
    "bfs": "MATCH (s:Node {id: $src}) CALL {algo:bfs}(s, 8, 'PROPAGATES_TO') YIELD nodes RETURN [n IN nodes | n.id] AS ids",
    "sppaths": "MATCH (c:Node {id: $src}), (s:Node {id: $dst}) CALL {algo:sppaths}({sourceNode: c, targetNode: s, "
               "relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, "
               "pathCount: 3}) YIELD path, pathWeight RETURN [n IN nodes(path) | n.id] AS ids, pathWeight AS w",
    "sspaths": "MATCH (s:Node {id: $src}) CALL {algo:sspaths}({sourceNode: s, relTypes: ['PROPAGATES_TO'], weightProp: "
               "'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path, pathWeight "
               "RETURN [n IN nodes(path) | n.id] AS ids, pathWeight AS w",
    "pagerank": "CALL {algo:pagerank}('Service', 'CALLS') YIELD node, score RETURN node.id AS id, score",
    "betweenness": "CALL {algo:betweenness}({nodeLabels: ['Service', 'Datastore'], relationshipTypes: ['CALLS'], "
                   "samplingSize: $n, samplingSeed: 42}) YIELD node, score RETURN node.id AS id, score",
    "harmonic": "CALL {algo:harmonic}({nodeLabels: ['Service', 'Datastore'], relationshipTypes: ['CALLS']}) "
                "YIELD node, score, reachable RETURN node.id AS id, score, reachable",
    "wcc": "CALL {algo:wcc}({nodeLabels: ['Service', 'Datastore', 'Table', 'KPI', 'Dashboard'], relationshipTypes: "
           "['PROPAGATES_TO']}) YIELD node, componentId RETURN node.id AS id, componentId AS c",
    "cdlp": "CALL {algo:cdlp}({nodeLabels: ['Incident', 'Symptom', 'Deploy', 'Service', 'Datastore', 'Transform', "
            "'Table'], relationshipTypes: ['HAS_SYMPTOM', 'CAUSED', 'CHANGED'], maxIterations: 20}) "
            "YIELD node, communityId RETURN node.id AS id, communityId AS c",
    "maxflow": "MATCH (s:Node) WHERE s.id IN $srcs WITH collect(s) AS srcs MATCH (t:Node {id: $dst}) "
               "CALL {algo:maxflow}({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], "
               "capacityProperty: 'cap'}) YIELD maxFlow RETURN maxFlow",
    "msf": "CALL {algo:msf}({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES'], objective: 'maximize', "
           "weightAttribute: 'w'}) YIELD edges RETURN [e IN edges | e.w] AS ws",
}

# extraction reads (engine connection; ORDER BY + SKIP/LIMIT pages, so the engine's RESULTSET_SIZE never truncates)
NODES_Q = ("MATCH (n:Node) WHERE any(l IN labels(n) WHERE l IN $labels) "
           "RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label ORDER BY id SKIP $skip LIMIT $lim")
EDGES_Q = ("MATCH (a:Node)-[r]->(b:Node) WHERE type(r) IN $types "
           "RETURN a.id AS a, b.id AS b, type(r) AS t, r.w AS w, r.cap AS cap, "
           "[x IN labels(a) WHERE x <> 'Node'][0] AS la, [x IN labels(b) WHERE x <> 'Node'][0] AS lb "
           "ORDER BY a, b, t SKIP $skip LIMIT $lim")


# ------------------------------------------------------------------ pure helpers (unit-tested, no engine, no NetworkX)
def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[max(0, math.ceil(q * len(xs)) - 1)], 3)


def tstats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "p99": pct(xs, 0.99),
            "max": round(max(xs), 3) if xs else None}


def top_k(scores: dict[str, float], k: int = TOP) -> list[str]:
    """Highest score first; ties broken by id so both sides order a tie the same way."""
    return [i for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def partition(assign: dict[str, object]) -> set[frozenset]:
    groups: dict[object, set] = {}
    for node, c in assign.items():
        groups.setdefault(c, set()).add(node)
    return {frozenset(g) for g in groups.values()}


def rel_close(a: float, b: float, tol: float = REL_TOL) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def compare_paths(falkor: list[tuple[list[str], float]], nx_paths: list[tuple[list[str], float]]) -> dict:
    """SPpaths: the same weights in order; where a weight occurs once on both sides, the same path."""
    fw = [round(w, 9) for _, w in falkor]
    nw = [round(w, 9) for _, w in nx_paths]
    same_paths = True
    for (fp, w), (npth, w2) in zip(falkor, nx_paths):
        if fw.count(round(w, 9)) == 1 and nw.count(round(w2, 9)) == 1 and fp != npth:
            same_paths = False
    return {"equal": fw == nw and same_paths, "falkor_weights": fw, "nx_weights": nw, "same_unique_paths": same_paths}


def compare_sspaths(falkor: list[tuple[list[str], float]], dist: dict[str, float], hops: dict[str, int],
                    src: str) -> dict:
    """SSpaths (pathCount is a global top-k by weight): every target whose shortest distance (on a path of ≤ 8 hops)
    is strictly below the largest returned weight must be returned with that distance as its minimum."""
    best: dict[str, float] = {}
    over_len = 0
    for ids, w in falkor:
        over_len += 1 if len(ids) - 1 > 8 else 0
        t = ids[-1]
        best[t] = min(w, best.get(t, math.inf))
    wmax = max((w for _, w in falkor), default=0.0)
    must = {t for t, d in dist.items() if t != src and d < wmax - 1e-12 and hops.get(t, 99) <= 8}
    missing = sorted(t for t in must if t not in best)
    wrong = sorted(t for t in must if t in best and not rel_close(best[t], dist[t], 1e-9))
    unknown = sorted(t for t in best if t not in dist)
    return {"equal": not missing and not wrong and not unknown and not over_len, "paths": len(falkor),
            "targets_returned": len(best), "targets_checked": len(must), "missing": missing[:10], "wrong": wrong[:10],
            "not_reachable_in_nx": unknown[:10], "over_8_hops": over_len, "largest_weight": wmax,
            "nx_reachable": len(dist) - 1}


# ------------------------------------------------------------------ engine side
def _engine():
    from faultline.graph import client

    return client.engine()


def resolve(text: str) -> str:
    from faultline.graph.algo import registry

    return re.sub(r"\{algo:([a-z_]+)\}", lambda m: registry.name(m.group(1)), text)


def used_mb() -> float:
    return float(_engine().connection.info("memory")["used_memory"]) / 2**20


def settled_used_mb(timeout_s: float = 20.0) -> float:
    last, end = used_mb(), time.time() + timeout_s
    while time.time() < end:
        time.sleep(1.0)
        now = used_mb()
        if abs(now - last) < 0.25:
            return now
        last = now
    return last


def falkor(g, key: str, params: dict, runs: int) -> tuple[list | None, dict]:
    """`runs` executions through GRAPH.RO_QUERY: engine-reported and wall ms; the last result set."""
    q = resolve(CALLS[key])
    eng, wall, rows, err = [], [], None, None
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            res = g.ro_query(q, params=params, timeout=TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001 - a TIMEOUT / engine error is a result, recorded
            err = f"{type(e).__name__}: {str(e)[:200]}"
            break
        wall.append((time.perf_counter() - t0) * 1000)
        eng.append(float(res.run_time_ms))
        rows = res.result_set
    return rows, {"runs": len(eng), "engine_ms": tstats(eng), "wall_ms": tstats(wall), **({"error": err} if err else {})}


def read_all(g, text: str, params: dict) -> list[list]:
    out, skip = [], 0
    while True:
        rows = g.ro_query(text, params={**params, "skip": skip, "lim": PAGE}, timeout=TIMEOUT_MS).result_set
        out += rows
        if len(rows) < PAGE:
            return out
        skip += PAGE


def nodes_of(g, labels: tuple[str, ...]) -> dict[str, str]:
    return {i: lb for i, lb in read_all(g, NODES_Q, {"labels": list(labels)})}


def edges_of(g, types: tuple[str, ...]) -> list[dict]:
    return [{"a": a, "b": b, "t": t, "w": w, "cap": cap, "la": la, "lb": lb}
            for a, b, t, w, cap, la, lb in read_all(g, EDGES_Q, {"types": list(types)})]


# ------------------------------------------------------------------ NetworkX side (imported lazily: eval-only group)
def _nx():
    try:
        import networkx as nx
    except ImportError as e:  # fail loudly: the comparator needs its dependency group
        raise SystemExit("networkx missing: run with `uv run --group comparator` (make algo10k)") from e
    return nx


def digraph(nodes, edges, weight: str | None = None, combine=min):
    """A DiGraph of `nodes` and `edges`; parallel edges collapse with `combine` on `weight` (min for path weights,
    sum for capacities). Returns (G, parallel edge count)."""
    nx = _nx()
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    par = 0
    for e in edges:
        a, b = e["a"], e["b"]
        if G.has_edge(a, b):
            par += 1
            if weight:
                G[a][b][weight] = combine(G[a][b][weight], float(e[weight] or 0.0))
            continue
        G.add_edge(a, b, **({weight: float(e[weight] or 0.0)} if weight else {}))
    return G, par


def nx_time(fn, runs: int = NX_RUNS) -> tuple[object, dict]:
    ms, out = [], None
    for i in range(runs):
        gc.collect()
        t0 = time.perf_counter()
        out = fn()
        ms.append((time.perf_counter() - t0) * 1000)
        if i == 0 and ms[0] > NX_SLOW_S * 1000:
            break
    return out, {"runs": len(ms), "ms": tstats(ms)}


def nx_bytes(build, fn=None, slow: bool = False) -> dict:
    """tracemalloc: bytes held by the built graph, then the peak extra bytes while the algorithm runs (not for a
    computation over NX_SLOW_S: it would be rerun several times slower under tracing)."""
    gc.collect()
    tracemalloc.start()
    try:
        G = build()
        graph_b = tracemalloc.get_traced_memory()[0]
        peak = None
        if fn is not None and not slow:
            tracemalloc.reset_peak()
            fn(G)
            peak = tracemalloc.get_traced_memory()[1] - graph_b
    finally:
        tracemalloc.stop()
    return {"graph_bytes": graph_b, "algo_peak_bytes": peak}


# ------------------------------------------------------------------ the workloads
def targets(label: str, services: int | None, golden: str) -> dict:
    """Sources and targets from the world config (evals/scale.py's planted incident), plus a historical deploy on
    the planted cause's component (read from the graph: deploys carry generated ids)."""
    import scale as S
    import scale_world as W
    from faultline.agent.weights import weights
    from faultline.ingest.clock import ANCHOR_MS

    w = W.world(services or W.SIZES[label])
    plan = S.plan_incident(w, ANCHOR_MS + 3 * 3_600_000, int(weights()["gate"]["window_min"]))
    g = _engine().select_graph(golden)

    def deploy_on(x: str | None) -> str | None:
        if not x:
            return None
        r = g.ro_query("MATCH (d:Deploy)-[:CHANGED]->(:Node {id: $x}) RETURN d.id ORDER BY d.id LIMIT 1", {"x": x}).result_set
        return r[0][0] if r else None

    c, t, hub = plan["cause_target"], plan["symptom"], plan["hub"]
    return {"cause_component": c, "symptom": t, "hub": hub, "deploy_on_cause": deploy_on(c), "deploy_on_hub": deploy_on(hub)}


def workload_params(tg: dict, n_cent: int) -> dict[str, list[tuple[str, str, dict]]]:
    """(tag, description, params) per procedure; the tag names the instance in latest.json keys."""
    hub = tg["hub"] or tg["cause_component"]
    sp = [("cause", f"{tg['deploy_on_cause']} → {tg['symptom']}", {"src": tg["deploy_on_cause"], "dst": tg["symptom"]})]
    if tg.get("deploy_on_hub"):
        sp.append(("hub", f"{tg['deploy_on_hub']} → {tg['symptom']} (a deploy on the global hub)",
                   {"src": tg["deploy_on_hub"], "dst": tg["symptom"]}))
    return {
        "bfs": [("hub", f"from the hub {hub}, 8 hops", {"src": hub})],
        "sppaths": [x for x in sp if x[2]["src"]],
        "sspaths": [("hub", f"from the hub {hub}, pathCount 1000", {"src": hub})],
        "pagerank": [("all", "Service / CALLS", {})],
        "betweenness": [("all", f"Service + Datastore / CALLS, exact (samplingSize {n_cent})", {"n": n_cent})],
        "harmonic": [("all", "Service + Datastore / CALLS", {})],
        "wcc": [("all", "failure-flow layer (Service, Datastore, Table, KPI, Dashboard)", {})],
        "cdlp": [("all", "incident families layer", {})],
        "maxflow": [("single", f"{tg['cause_component']} → {tg['symptom']}",
                     {"srcs": [tg["cause_component"]], "dst": tg["symptom"]}),
                    ("joint", f"joint {{{tg['cause_component']}, {hub}}} → {tg['symptom']}",
                     {"srcs": sorted({tg["cause_component"], hub}), "dst": tg["symptom"]})],
        "msf": [("all", "Person / COLLABORATES, maximise w", {})],
    }


class Inputs:
    """The extracted inputs, read once from the 10k graph (engine connection)."""

    def __init__(self, g):
        t0 = time.perf_counter()
        self.prop = edges_of(g, ("PROPAGATES_TO",))
        self.chain = edges_of(g, ("CHANGED", "GATES", "PROPAGATES_TO"))
        self.calls = [e for e in edges_of(g, ("CALLS",)) if e["la"] in CENT_LABELS and e["lb"] in CENT_LABELS]
        self.cent_nodes = nodes_of(g, CENT_LABELS)
        self.wcc_nodes = nodes_of(g, WCC_LABELS)
        self.lpa_nodes = nodes_of(g, LPA_LABELS)
        self.lpa_edges = [e for e in edges_of(g, LPA_RELS) if e["la"] in LPA_LABELS and e["lb"] in LPA_LABELS]
        self.persons = nodes_of(g, ("Person",))
        self.collab = [e for e in edges_of(g, ("COLLABORATES",)) if e["la"] == "Person" and e["lb"] == "Person"]
        self.read_s = round(time.perf_counter() - t0, 2)

    def union(self) -> tuple[dict[str, str], list[dict]]:
        """Every workload's input together: the graph both systems hold for the memory comparison."""
        nodes: dict[str, str] = {}
        for d in (self.cent_nodes, self.wcc_nodes, self.lpa_nodes, self.persons):
            nodes.update(d)
        edges: dict[tuple, dict] = {}
        for e in self.chain + self.calls + self.lpa_edges + self.collab:
            nodes.setdefault(e["a"], e["la"])
            nodes.setdefault(e["b"], e["lb"])
            edges[(e["a"], e["b"], e["t"])] = e
        return nodes, list(edges.values())


def run_workload(key: str, g, inp: Inputs, params_list: list[tuple[str, str, dict]], runs: int, proj=None) -> list[dict]:
    """One procedure: FalkorDB on the product graph (and on the projection), NetworkX once on the extracted input, and
    each FalkorDB answer checked against NetworkX's by the pre-registered criterion."""
    nx = _nx()
    rows_out = []
    for tag, inst, params in params_list:
        rec: dict = {"procedure": key, "tag": tag, "instance": inst, "params": params, "criterion": CRITERIA[key]}
        frows, rec["falkor"] = falkor(g, key, params, runs)
        prow = None
        if proj is not None:
            prow, rec["falkor_projection"] = falkor(proj, key, params, runs)
        if frows is None:
            rec["equal"] = None
            rows_out.append(rec)
            continue
        check, rec["nx"] = nx_side(key, nx, inp, params)
        rec.update(check(frows))
        if prow is not None:
            pc = check(prow)
            rec["equal_on_projection"] = pc["equal"]
        rows_out.append(rec)
    return rows_out


def _info(G, t: dict, mem: dict, **extra) -> dict:
    return {**t, **mem, **extra, "input": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}}


def nx_side(key: str, nx, inp: Inputs, params: dict):
    """NetworkX on the extracted input, timed once per workload; returns (check(falkor_rows) → dict, nx info)."""
    if key == "bfs":
        def build():
            return digraph(set(), inp.prop)[0]
        G = build()
        src = params["src"]
        res, t = nx_time(lambda: set(nx.single_source_shortest_path_length(G, src, cutoff=8)) - {src})

        def check(rows):
            f = set(rows[0][0]) if rows else set()
            return {"equal": f == res, "falkor_count": len(f), "nx_count": len(res)}
        return check, _info(G, t, nx_bytes(build, lambda G: nx.single_source_shortest_path_length(G, src, cutoff=8)))
    if key == "sppaths":
        def build():
            return digraph(set(), inp.chain, "w", min)[0]
        G, par = digraph(set(), inp.chain, "w", min)

        def k_paths(G=G):
            out = []
            if params["src"] not in G or params["dst"] not in G:
                return out
            try:
                for i, pth in enumerate(nx.shortest_simple_paths(G, params["src"], params["dst"], weight="w")):
                    if len(pth) - 1 <= 8:
                        out.append((pth, sum(G[a][b]["w"] for a, b in zip(pth, pth[1:]))))
                    if len(out) == 3 or i > 1000:
                        break
            except nx.NetworkXNoPath:
                pass
            return out
        res, t = nx_time(k_paths)

        def check(rows):
            f = sorted(((list(ids), float(w)) for ids, w in rows), key=lambda x: x[1])
            return {**compare_paths(f, res), "parallel_edges_collapsed": par}
        return check, _info(G, t, nx_bytes(build, lambda G: k_paths(G)))
    if key == "sspaths":
        def build():
            return digraph(set(), inp.prop, "w", min)[0]
        G = build()
        src = params["src"]
        (dist, paths), t = nx_time(lambda: nx.single_source_dijkstra(G, src, weight="w"))
        hops = {k: len(v) - 1 for k, v in paths.items()}

        def check(rows):
            return compare_sspaths([(list(ids), float(w)) for ids, w in rows], dist, hops, src)
        return check, _info(G, t, nx_bytes(build, lambda G: nx.single_source_dijkstra(G, src, weight="w")))
    if key == "pagerank":
        svc = [i for i, lb in inp.cent_nodes.items() if lb == "Service"]
        ed = [e for e in inp.calls if e["la"] == "Service" and e["lb"] == "Service"]

        def build():
            return digraph(svc, ed)[0]
        G = build()
        res, t = nx_time(lambda: nx.pagerank(G, alpha=0.85))

        def check(rows):
            f = {i: float(sc) for i, sc in rows}
            diff = max((abs(f.get(k, 0.0) - v) for k, v in res.items()), default=0.0)
            return {"equal": top_k(f) == top_k(res), "falkor_top": top_k(f), "nx_top": top_k(res),
                    "max_abs_diff": diff, "nodes_compared": len(res)}
        return check, _info(G, t, nx_bytes(build, lambda G: nx.pagerank(G, alpha=0.85)), impl="networkx.pagerank (scipy)")
    if key in ("betweenness", "harmonic"):
        def build():
            G = digraph(list(inp.cent_nodes), inp.calls)[0]
            return G if key == "betweenness" else G.reverse(copy=True)
        G = build()
        fn = ((lambda G: nx.betweenness_centrality(G, normalized=False)) if key == "betweenness"
              else (lambda G: nx.harmonic_centrality(G)))
        res, t = nx_time(lambda: fn(G))
        slow = t["ms"]["p50"] > NX_SLOW_S * 1000
        mem = nx_bytes(build, fn, slow)
        if key == "betweenness":
            def check(rows):
                f = {i: float(sc) for i, sc in rows}
                bad = [k for k, v in res.items() if not rel_close(f.get(k, math.nan), v)]
                return {"equal": not bad and len(f) == len(res), "mismatched": len(bad), "examples": bad[:5],
                        "falkor_top": top_k(f), "nx_top": top_k(res)}
            return check, _info(G, t, mem)

        def check(rows):
            f = {i: float(sc) for i, sc, _ in rows}
            errs = [abs(f[k] - v) / v for k, v in res.items() if v > 0 and k in f]
            return {"equal": set(top_k(f)) == set(top_k(res)), "falkor_top": top_k(f), "nx_top": top_k(res),
                    "max_rel_error": round(max(errs), 6) if errs else 0.0,
                    "mean_rel_error": round(statistics.fmean(errs), 6) if errs else 0.0, "approximate": True}
        return check, _info(G, t, mem, direction="NetworkX on the reversed graph (FalkorDB sums distances from the node)")
    if key == "wcc":
        ed = [e for e in inp.prop if e["la"] in WCC_LABELS and e["lb"] in WCC_LABELS]

        def build():
            return digraph(list(inp.wcc_nodes), ed)[0]
        G = build()
        res, t = nx_time(lambda: {frozenset(c) for c in nx.weakly_connected_components(G)})

        def check(rows):
            f = partition({i: c for i, c in rows})
            return {"equal": f == res, "falkor_components": len(f), "nx_components": len(res)}
        return check, _info(G, t, nx_bytes(build, lambda G: list(nx.weakly_connected_components(G))))
    if key == "cdlp":
        def build():
            return digraph(list(inp.lpa_nodes), inp.lpa_edges)[0].to_undirected()
        G = build()
        res, t = nx_time(lambda: list(nx.community.label_propagation_communities(G)))

        def check(rows):
            return {"equal": None, "falkor_communities": len(partition({i: c for i, c in rows})),
                    "nx_communities": len(res)}
        return check, _info(G, t, nx_bytes(build, lambda G: list(nx.community.label_propagation_communities(G))),
                            impl="networkx.community.label_propagation_communities (semi-synchronous; another update rule)")
    if key == "maxflow":
        srcs, dst = tuple(params["srcs"]), params["dst"]

        def build():
            G, _ = digraph(set(), inp.prop, "cap", lambda x, y: x + y)
            big = sum(float(e["cap"] or 0.0) for e in inp.prop) + 1.0
            for s in srcs:
                G.add_edge("__source__", s, cap=big)
            return G
        G = build()
        res, t = nx_time(lambda: float(nx.maximum_flow_value(G, "__source__", dst, capacity="cap")))

        def check(rows):
            f = float(rows[0][0]) if rows else 0.0
            return {"equal": abs(f - res) <= 1e-9 * max(1.0, abs(f)), "falkor_value": f, "nx_value": res}
        info = _info(G, t, nx_bytes(build, lambda G: nx.maximum_flow_value(G, "__source__", dst, capacity="cap")),
                     impl="networkx.maximum_flow_value (preflow-push) with a super-source")
        info["input"] = {"nodes": G.number_of_nodes() - 1, "edges": G.number_of_edges() - len(srcs)}
        return check, info
    if key == "msf":
        def build():
            U = nx.Graph()
            U.add_nodes_from(inp.persons)
            for e in inp.collab:   # both directions of a collaboration: the undirected edge keeps the larger weight
                w = float(e["w"] or 0.0)
                if not U.has_edge(e["a"], e["b"]) or U[e["a"]][e["b"]]["w"] < w:
                    U.add_edge(e["a"], e["b"], w=w)
            return U
        U = build()
        res, t = nx_time(lambda: [d["w"] for _, _, d in nx.maximum_spanning_edges(U, algorithm="kruskal", weight="w", data=True)])

        def check(rows):
            fw = [float(w) for r in rows for w in r[0]]
            return {"equal": len(fw) == len(res) and abs(sum(fw) - sum(res)) <= 1e-6 * max(1.0, sum(res)),
                    "falkor_edges": len(fw), "nx_edges": len(res), "falkor_total": round(sum(fw), 6),
                    "nx_total": round(sum(res), 6)}
        return check, _info(U, t, nx_bytes(build, lambda U: list(nx.maximum_spanning_edges(U, algorithm="kruskal", weight="w"))))
    raise KeyError(key)


# ------------------------------------------------------------------ memory of the same graph
def build_projection(db, name: str, nodes: dict[str, str], edges: list[dict]) -> dict:
    """The union input written by the product's writers (graph/writes.py) into a scratch graph; settled engine
    used_memory before and after."""
    from faultline.graph import writes

    import scale_world as W

    before = settled_used_mb()
    g = db.select_graph(name)
    t0 = time.perf_counter()
    W.ensure_key(db, name)
    writes.apply_schema(g)
    by_label: dict[str, list[dict]] = {}
    for i, lb in nodes.items():
        by_label.setdefault(lb, []).append({"id": i})
    for lb, rows in sorted(by_label.items()):
        writes.upsert_nodes(g, lb, rows)
    by_type: dict[tuple, list[dict]] = {}
    for e in edges:
        props = {k: float(e[k]) for k in ("w", "cap") if e.get(k) is not None}
        by_type.setdefault((e["t"], e["la"], e["lb"]), []).append({"src": e["a"], "dst": e["b"], "props": props})
    for (t, la, lb), rows in sorted(by_type.items()):
        writes.upsert_edges(g, t, la, lb, rows)
    build_s = time.perf_counter() - t0
    after = settled_used_mb()
    mem = db.connection.execute_command("GRAPH.MEMORY", "USAGE", name)
    return {"graph": name, "nodes": len(nodes), "edges": len(edges), "build_s": round(build_s, 2),
            "used_mb_delta": round(after - before, 3), "bytes": int((after - before) * 2**20),
            "graph_memory_usage_mb": dict(zip(mem[::2], mem[1::2])).get("total_graph_sz_mb")}


def nx_union_bytes(nodes: dict[str, str], edges: list[dict]) -> dict:
    nx = _nx()

    def build():
        G = nx.MultiDiGraph()
        for i, lb in nodes.items():
            G.add_node(i, label=lb)
        for e in edges:
            G.add_edge(e["a"], e["b"], key=e["t"], **{k: float(e[k]) for k in ("w", "cap") if e.get(k) is not None})
        return G

    b = nx_bytes(build)
    return {"bytes": b["graph_bytes"], "nodes": len(nodes), "edges": len(edges), "impl": "networkx.MultiDiGraph"}


# ------------------------------------------------------------------ the run
def run(label: str, services: int | None, runs: int, keep: bool, projection: bool, reason: str, progress: bool) -> dict:
    import scale_world as W
    from faultline.graph import copy as gcopy
    from faultline.graph.algo import registry
    from faultline.graph.tenant import golden_graph, scratch_graph

    nx = _nx()
    db = _engine()
    tenant = W.tenant_for(label)
    golden = golden_graph(tenant)
    n_services = services or W.SIZES[label]
    meta = registry.resolved_meta()
    out: dict = {"bench": "algo10k", "engine": meta.get("engine"), "digest": meta.get("digest"), "size": label,
                 "services": n_services, "runs": runs, "nx_runs": NX_RUNS, "networkx": nx.__version__, "reason": reason,
                 "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "procedures": {k: v["name"] for k, v in registry.resolved().items()}}
    seeded_here = False
    proj_name = scratch_graph(tenant, f"algoproj_{uuid.uuid4().hex[:8]}")
    try:
        if golden not in set(db.list_graphs()):
            if progress:
                print(f"[algo] seeding {golden} ({n_services} services) …", file=sys.stderr, flush=True)
            out["seed"] = W.seed(n_services, tenant, golden, progress=progress)
            seeded_here = True
        g = db.select_graph(golden)
        st = g.ro_query("CALL db.meta.stats()")
        row = dict(zip([h[1] if isinstance(h, (list, tuple)) else h for h in st.header], st.result_set[0]))
        out["graph"] = {"name": golden, "nodes": int(row["nodeCount"]), "edges": int(row["relCount"])}
        tg = targets(label, services, golden)
        out["targets"] = tg
        inp = Inputs(g)
        out["extract_s"] = inp.read_s
        out["params_pool"] = {"centrality_nodes": len(inp.cent_nodes)}
        proj = None
        if projection:
            if progress:
                print("[algo] writing the projection (every workload's input) …", file=sys.stderr, flush=True)
            nodes, edges = inp.union()
            out["memory"] = {"falkordb": build_projection(db, proj_name, nodes, edges), "networkx": nx_union_bytes(nodes, edges)}
            m = out["memory"]
            elems = m["falkordb"]["nodes"] + m["falkordb"]["edges"]
            m["falkordb_bytes_per_elem"] = round(m["falkordb"]["bytes"] / elems, 1) if elems else None
            m["networkx_bytes_per_elem"] = round(m["networkx"]["bytes"] / elems, 1) if elems else None
            m["ratio_nx_over_falkordb"] = (round(m["networkx"]["bytes"] / m["falkordb"]["bytes"], 2)
                                           if m["falkordb"]["bytes"] > 0 else None)
            proj = db.select_graph(proj_name)
        out["workloads"] = []
        for key, plist in workload_params(tg, len(inp.cent_nodes)).items():
            if progress:
                print(f"[algo] {key} …", file=sys.stderr, flush=True)
            recs = run_workload(key, g, inp, plist, runs, proj)
            out["workloads"] += recs
            if progress:
                for r in recs:
                    f = (r.get("falkor") or {}).get("engine_ms") or {}
                    n = ((r.get("nx") or {}).get("ms")) or {}
                    print(f"    {r['instance']}: equal={r.get('equal')} falkor p50 {f.get('p50')} ms, networkx p50 "
                          f"{n.get('p50')} ms {r.get('falkor', {}).get('error', '')}", file=sys.stderr, flush=True)
    finally:
        gcopy.delete_if_exists(db, proj_name)
        if seeded_here and not keep:
            gcopy.delete_if_exists(db, golden)
        out["kept"] = sorted(n for n in db.list_graphs() if n in (golden, proj_name))
        out["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def main() -> int:
    import scale_world as W

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--size", default="10k", choices=list(W.SIZES))
    ap.add_argument("--services", type=int, default=None, help="override the service count (smoke: 200 = one unit)")
    ap.add_argument("--runs", type=int, default=R)
    ap.add_argument("--keep", action="store_true", help="keep a golden graph seeded here (default: delete it)")
    ap.add_argument("--no-projection", action="store_true")
    ap.add_argument("--reason", default="M20 Wave B pre-registered run (PREREGISTRATION addendum 2026-10-17 21:10 IST)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    out = run(a.size, a.services, a.runs, a.keep, not a.no_projection, a.reason, not a.quiet)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    comparable = [w for w in out.get("workloads", []) if w.get("equal") is not None]
    print(f"{sum(1 for w in comparable if w['equal'])}/{len(comparable)} comparable workloads give the same answers; "
          f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
