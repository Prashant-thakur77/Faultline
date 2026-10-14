"""FalkorDB vs a flat store, freshness and depth (PREREGISTRATION amendment 2026-10-13).

(a) lookups (pre-registered "blast radius, 1–6 hops": Q-BLAST-1/2 run to their shipped depth 8, and Q-BLAST-2's
    per-node hop distances are compared node by node, which covers every depth up to 8): the gate's reachability and shortest causal path, run as the product runs them (the RO wrapper over the real
    templates: Q-BLAST-1 algo.BFS reach set, Q-BLAST-2 hop distances, Q-GATE-1 algo.SPpaths shortest causal path) and as
    DuckDB recursive SQL over the same edge table exported from the same graph (an eval-only comparator, never in the
    product). On acme (golden copy) and the 1k-service federation (seeded into a scratch graph, deleted afterwards).
    p50/p95 over 20 timed runs per lookup instance after one warm-up, and result equality (same reached set in the same
    order under the template's LIMIT, same hop distances, same shortest causal path length or both "no path").
    FalkorDB times are reported twice: the product's round trip (RO.run: loopback network + parsing) and the engine's
    own execution time; DuckDB runs in-process. The SQL computes only the length of the shortest path (the favourable
    comparator); Q-GATE-1 also returns the three paths. Every edge weight `w` is 1 in these graphs, so the least-weight
    path is the fewest-hops path. Max flow has no SQL equivalent and is not compared.
(b) freshness: ms from writing an alert (writes.raise_alert) or an error-rate window (writes.upsert_nodes) as the engine
    user to its first sighting by the read-only decision query that consumes it (Q-ALERT-1 / Q-MW-1, separate RO
    connection pool), p50/p95 over 50 writes each, on a GRAPH.COPY of golden_acme. One server: this is
    read-after-acknowledge latency, not replication lag.
(c) depth: on the 100 held-out gate-bench worlds, correct verdicts grouped by the hop distance from the true cause's
    component to the symptom (golden graph, Q-BLAST-2), next to arm T (telemetry only) on the same worlds.

    PYTHONPATH=backend uv run python evals/perf_vs_flat.py [--parts lookups,freshness,depth] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if __import__("importlib.util").util.find_spec("gate_bench") is None:
    sys.path.insert(0, str(ROOT / "evals"))

import duckdb  # noqa: E402  (eval-only comparator; the product never imports it outside warehouse.py)

from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph import writes  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.templates import load  # noqa: E402
from faultline.mcp_server import tools as T  # noqa: E402

SEED = 20261013
RUNS = 20
INSTANCES = 10           # lookup instances per lookup kind and graph
FRESH_N = 50
CAUSAL = ("CHANGED", "GATES", "PROPAGATES_TO")
PAGE = 50_000            # the engine's RESULTSET_SIZE is 100000: export in pages

SQL_REACH = """
WITH RECURSIVE r(id, d) AS (
  SELECT dst, 1 FROM e WHERE src = $s AND typ = 'PROPAGATES_TO'
  UNION
  SELECT e.dst, r.d + 1 FROM r JOIN e ON e.src = r.id AND e.typ = 'PROPAGATES_TO' WHERE r.d < 8)
SELECT id, min(d) AS hops FROM r WHERE id <> $s GROUP BY id"""
SQL_PATH = """
WITH RECURSIVE r(id, d) AS (
  SELECT dst, 1 FROM e WHERE src = $c AND typ IN ('CHANGED', 'GATES', 'PROPAGATES_TO')
  UNION
  SELECT e.dst, r.d + 1 FROM r JOIN e ON e.src = r.id AND e.typ IN ('CHANGED', 'GATES', 'PROPAGATES_TO') WHERE r.d < 8)
SELECT min(d) FROM r WHERE id = $t"""


def pct(xs: list[float], q: float) -> float:
    """Nearest-rank percentile (the scale bench's rule)."""
    s = sorted(xs)
    return round(s[max(0, min(len(s) - 1, -(-len(s) * q // 100) - 1))], 3) if s else None


def _stats(xs: list[float]) -> dict:
    return {"p50": pct(xs, 50), "p95": pct(xs, 95), "n": len(xs)}


# ------------------------------------------------------------------ (a) lookups
def export_edges(graph: str) -> list[tuple[str, str, str]]:
    g = gclient.engine().select_graph(graph)
    out: list[tuple[str, str, str]] = []
    while True:
        rows = g.ro_query("MATCH (a:Node)-[r]->(b:Node) WHERE type(r) IN $types RETURN a.id, b.id, type(r) "
                          "ORDER BY a.id, b.id, type(r) SKIP $skip LIMIT $page",
                          {"types": list(CAUSAL), "skip": len(out), "page": PAGE}, timeout=10_000).result_set
        out += [tuple(r) for r in rows]
        if len(rows) < PAGE:
            return out


def _falkor(ro: RO, tid: str, params: dict) -> tuple[list[dict], float, float]:
    """(rows, round-trip ms through the product's RO wrapper, engine execution ms of the same text)."""
    r = ro.run(tid, params, timeout_ms=10_000)
    eng = gclient.engine().select_graph(ro.graph_name).ro_query(load(tid).text, params, timeout=10_000)
    return r.rows, r.ms, float(eng.run_time_ms)


def _time(f, runs: int) -> list[float]:
    f()
    out = []
    for _ in range(runs):
        t0 = time.perf_counter()
        f()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def lookups(tenant: str, graph: str, runs: int = RUNS, instances: int = INSTANCES, seed: int = SEED) -> dict:
    t0 = time.perf_counter()
    edges = export_edges(graph)
    con = duckdb.connect()
    con.execute("CREATE TABLE e(src VARCHAR, dst VARCHAR, typ VARCHAR)")
    con.executemany("INSERT INTO e VALUES (?, ?, ?)", edges)
    con.execute("CREATE INDEX e_src ON e(src)")
    export_s = round(time.perf_counter() - t0, 2)
    rnd = random.Random(f"{seed}:{graph.split('_')[1]}")
    prop_src = sorted({s for s, _, t in edges if t == "PROPAGATES_TO"})
    change_src = sorted({s for s, _, t in edges if t in ("CHANGED", "GATES")})
    nodes = sorted({x for s, d, _ in edges for x in (s, d)})
    sources = rnd.sample(prop_src, min(instances, len(prop_src)))
    ro = RO(tenant, graph)

    def sql_reach(s: str) -> list[tuple[str, int]]:
        return con.execute(SQL_REACH, {"s": s}).fetchall()

    def sql_path(c: str, t: str):
        return con.execute(SQL_PATH, {"c": c, "t": t}).fetchone()[0]

    pairs = []
    for c in rnd.sample(change_src, min(instances, len(change_src))):
        reach = sorted({row[0] for row in con.execute(SQL_PATH.replace("SELECT min(d) FROM r WHERE id = $t",
                                                                          "SELECT DISTINCT id FROM r"), {"c": c}).fetchall()})
        # half the pairs have a causal path (a reached node), half are drawn from every node (mostly "no path")
        pairs.append((c, rnd.choice(reach) if reach and len(pairs) % 2 == 0 else rnd.choice(nodes)))
    res: dict = {"edges": len(edges), "nodes_with_edges": len(nodes), "export_s": export_s, "lookups": {}}
    kinds = {
        "reach_set": ("Q-BLAST-1", [{"id": s} for s in sources],
                      lambda p: [r["id"] for r in ro.run("Q-BLAST-1", p).rows],
                      lambda p: [x for x, _ in sorted(sql_reach(p["id"]))][:100]),
        "hop_distance": ("Q-BLAST-2", [{"id": s} for s in sources],
                         lambda p: [(r["id"], r["hops"]) for r in ro.run("Q-BLAST-2", p).rows],
                         lambda p: sorted(sql_reach(p["id"]), key=lambda x: (x[1], x[0]))[:100]),
        "shortest_causal_path": ("Q-GATE-1", [{"cause": c, "symptom": t} for c, t in pairs],
                                 lambda p: min((r["hops"] for r in ro.run("Q-GATE-1", p).rows), default=None),
                                 lambda p: sql_path(p["cause"], p["symptom"])),
    }
    for kind, (tid, params, f_res, s_res) in kinds.items():
        rt, eng, sq, equal, found = [], [], [], 0, 0
        for p in params:
            same = f_res(p) == s_res(p)
            equal += same
            found += bool(f_res(p))
            rt += _time(lambda: ro.run(tid, p, timeout_ms=10_000), runs)
            g = gclient.engine().select_graph(graph)
            text = load(tid).text
            eng += [float(g.ro_query(text, p, timeout=10_000).run_time_ms) for _ in range(runs)]
            sq += _time(lambda: s_res(p), runs)
        res["lookups"][kind] = {"template": tid, "instances": len(params), "equal": equal, "non_empty": found,
                                "falkordb_roundtrip_ms": _stats(rt), "falkordb_engine_ms": _stats(eng),
                                "duckdb_sql_ms": _stats(sq)}
    con.close()
    res["seconds"] = round(time.perf_counter() - t0, 1)
    return res


def lookups_all(progress: bool = True) -> dict:
    import scale_world as W
    from faultline.graph.tenant import eval_graph, golden_graph

    out = {"acme": lookups("acme", golden_graph("acme"))}
    if progress:
        print(f"[perf] acme: {json.dumps({k: v['equal'] for k, v in out['acme']['lookups'].items()})}", file=sys.stderr)
    tenant = W.tenant_for("1k")
    graph = eval_graph(tenant, "perf", "flat", "1k", 1) + f"_{uuid.uuid4().hex[:8]}"
    try:
        W.seed(W.SIZES["1k"], tenant, graph)
        out["1k"] = lookups(tenant, graph)
        out["1k"]["context_pack"] = pack_cost(tenant, graph)
    finally:
        gcopy.delete_if_exists(gclient.engine(), graph)
    if progress:
        print(f"[perf] 1k: {json.dumps({k: v['equal'] for k, v in out['1k']['lookups'].items()})}", file=sys.stderr)
    return out


def pack_cost(tenant: str, graph: str, n: int = 10, seed: int = SEED) -> dict:
    """Addendum: context_pack build time at 1k services (default ranking, 1,000 tokens), for n seeded alerting services."""
    from faultline.mcp_server import context as mcpctx

    services = sorted(r[0] for r in gclient.engine().select_graph(graph).ro_query(
        "MATCH (s:Service) RETURN s.id ORDER BY s.id", timeout=10_000).result_set)
    picks = random.Random(f"{seed}:pack").sample(services, min(n, len(services)))
    ms, pools, packs = [], [], []
    token = mcpctx.bind(tenant, run_id=None, graph=graph)
    try:
        for s in picks:
            t0 = time.perf_counter()
            r = T.context_pack(text=f"{s} errors are elevated", targets=[s], budget_tokens=1000)
            ms.append((time.perf_counter() - t0) * 1000)
            if "error" in r:
                raise RuntimeError(f"context_pack on {s}: {r['error']}")
            pools.append(len(r["pool"]))
            packs.append(len(r["rows"]))
    finally:
        mcpctx.unbind(token)
    return {"alerts": len(picks), "ms": _stats(ms), "pool_p50": statistics.median(pools), "pack_p50": statistics.median(packs)}


# ------------------------------------------------------------------ (b) freshness
def freshness(n: int = FRESH_N) -> dict:
    """Two writes the decisions depend on, each timed from the start of the engine-user write to its first sighting by
    the read-only decision query that consumes it (separate RO connection pool): an alert (writes.raise_alert →
    INTAKE's Q-ALERT-1) and an error-rate window (writes.upsert_nodes, as the simulator writes it → Q-MW-1)."""
    from faultline.graph.tenant import eval_graph, golden_graph
    from faultline.ingest.clock import ANCHOR_MS

    db = gclient.engine()
    graph = eval_graph("acme", "perf", "fresh", "alerts", 1) + f"_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, golden_graph("acme"), graph, deadline_s=120)
    out: dict = {}
    try:
        g = db.select_graph(graph)
        ro = RO("acme", graph)
        target = ro.run("Q-BLAST-1", {"id": "checkout"}).rows[0]["id"]

        def alert(i: int, at: int) -> tuple:
            aid = f"al-fresh-{i:03d}"
            return (lambda: writes.raise_alert(g, id=aid, target=target, metric="error_rate", at=at),
                    lambda: any(r["id"] == aid for r in ro.run("Q-ALERT-1", {"since": at - 1, "until": at + 1}).rows))

        def window(i: int, at: int) -> tuple:
            row = {"id": f"mw-fresh-{i:03d}", "target_id": target, "metric": "error_rate", "minute": 0, "at": at,
                   "value": 0.5, "kind": "live"}
            return (lambda: writes.upsert_nodes(g, "MetricWindow", [row]),
                    lambda: any(r["at"] == at for r in ro.run("Q-MW-1", {"target": target, "metric": "error_rate",
                                                                         "since": at - 1, "until": at + 1}).rows))

        for kind, make in (("alert", alert), ("window", window)):
            write_ms, total_ms, polls = [], [], []
            for i in range(n):
                at = ANCHOR_MS + 30 * 86_400_000 + i * 60_000   # a day no seeded alert or window uses
                write, seen = make(i, at)
                t0 = time.perf_counter()
                write()
                t1 = time.perf_counter()
                k = 0
                while True:
                    k += 1
                    if seen():
                        break
                    if time.perf_counter() - t0 > 5:
                        raise RuntimeError(f"{kind} {i} not visible to its read-only query after 5 s")
                t2 = time.perf_counter()
                write_ms.append((t1 - t0) * 1000)
                total_ms.append((t2 - t0) * 1000)
                polls.append(k)
            out[kind] = {"writes": n, "write_ms": _stats(write_ms), "write_to_visible_ms": _stats(total_ms),
                         "reads_until_visible_max": max(polls), "first_read_saw_it": sum(1 for k in polls if k == 1)}
    finally:
        gcopy.delete_if_exists(db, graph)
    return out


# ------------------------------------------------------------------ (c) depth
def depth(gate_detail: list[dict] | None = None, t_rows: list[dict] | None = None, progress: bool = True) -> dict:
    import gate_bench
    import mismatch_eval
    from faultline.graph.tenant import golden_graph

    cases = gate_bench.generate(seed=20261015)
    if gate_detail is None:
        gate_detail = gate_bench.run(seed=20261015)["cases_detail"]
    if t_rows is None:
        t_rows = [{"id": r["id"], "score": r["score"]} for r in map(mismatch_eval.arm_t_case, cases)]
    gate = {r["id"]: r["correct"] for r in gate_detail}
    tsc = {r["id"]: r["score"] for r in t_rows}
    groups: dict[str, dict] = {}
    for c in cases:
        exp = c["expected"]
        if exp["outcome"] != "CONFIRMED":
            key = "no true cause"
        else:
            comp = next(x["target"] for x in c["spec"]["inject"] if x["change"] == exp["cause"])
            if comp == c["symptom"]:
                key = "0"
            else:
                rows = RO(c["spec"]["tenant"], golden_graph(c["spec"]["tenant"])).run("Q-BLAST-2", {"id": comp}).rows
                key = str(next((r["hops"] for r in rows if r["id"] == c["symptom"]), "unreached"))
        g = groups.setdefault(key, {"cases": 0, "gate_correct": 0, "arm_t_score": 0.0})
        g["cases"] += 1
        g["gate_correct"] += bool(gate.get(c["id"]))
        g["arm_t_score"] = round(g["arm_t_score"] + tsc.get(c["id"], 0.0), 2)
    order = sorted(groups, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k))
    if progress:
        print(f"[perf] depth: {json.dumps({k: groups[k] for k in order})}", file=sys.stderr)
    return {"groups": {k: groups[k] for k in order}}


def run(parts=("lookups", "freshness", "depth"), gate_detail=None, t_rows=None, progress: bool = True) -> dict:
    t0 = time.perf_counter()
    out: dict = {}
    if "lookups" in parts:
        out["lookups"] = lookups_all(progress)
    if "freshness" in parts:
        out["freshness"] = freshness()
        if progress:
            print(f"[perf] freshness: {json.dumps(out['freshness'])}", file=sys.stderr)
    if "depth" in parts:
        out["depth"] = depth(gate_detail, t_rows, progress)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="lookups,freshness,depth")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(tuple(p for p in a.parts.split(",") if p))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
