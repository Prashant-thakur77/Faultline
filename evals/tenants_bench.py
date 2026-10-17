"""Tenant density, isolation and concurrent investigators on ONE pinned FalkorDB engine (M20 Wave B).

Pre-registered in evals/PREREGISTRATION.md (addendum 2026-10-17, 21:10 IST). FalkorDB markets "10K+ multi-graphs
(tenants)" and p99 under N clients; this bench measures what Faultline's own tenants cost and how its gate reads
behave when many investigators run at once, on the engine and configuration the product ships.

    make tenants-bench                                    # the pre-registered run → evals/results/tenants_bench.json
    PYTHONPATH=backend uv run python evals/tenants_bench.py --steps 2,3 --total-steps 5,6 --levels 1,4 \
        --duration 2 --warmup 1 --k 20 --cmd-sample 3 --out /tmp/x.json      # a tiny smoke variant

1. **Density.** Tenants `dens0001`, … get one graph each, `eval_<t>_bench`, made with the same steps as
   graph/copy.copy_graph (GRAPH.COPY, ready flag, schema re-applied). Phase A, product tenants: copies of `golden_acme`
   in steps 25 → 50 (capped there by amendment 2, to leave the guard's headroom to phase B). Phase B, small tenants: copies of `golden_densmini` (the failure-flow layer of
   golden_acme only, written once by the product's writers with the full schema) until the total reaches 250 → 500 →
   1,000. Every step runs only if the projected engine memory stays under the pre-registered ceiling (amendment
   2026-10-17, about 21:30 IST: a product tenant costs ~14 MB, so ~100 fit). MB per tenant per kind from INFO used_memory
   deltas (GRAPH.MEMORY USAGE rounds to whole MB and misses most index memory), copy time per tenant.
2. **Isolation.** One ACL user `ro_<t>` per tenant with exactly the `ro_` rules of deploy/users.acl.template; K
   cross-tenant reads that must all be refused (NOPERM), K own-graph reads that must succeed (so a refusal is not a
   broken login), forbidden commands on a sample of tenants, and the application layer's own refusal (RO wrapper).
3. **Concurrency.** M ∈ {1, 8, 32, 64} parallel investigators, each repeating a gate step (Q-GATE-1, Q-GATE-3,
   Q-BLAST-1) on a random tenant through the product's RO wrapper as that tenant's ACL user. Client processes ×
   threads, a warm-up, a measured window; throughput, p50/p95/p99, errors by class, engine and client CPU.
Everything the bench creates (graphs, ACL users) is deleted in a `finally`, and the bench checks nothing remains.
The ACL password is random, held in memory and in the worker processes' environment only, never printed or written.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import re
import secrets
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import scale_world as W  # noqa: E402

OUT = ROOT / "evals" / "results" / "tenants_bench.json"
SRC = "golden_acme"
SEED = 20261017
STEPS = (25, 50)                       # phase A: product tenants (copies of golden_acme); capped (amendment 2)
TOTAL_STEPS = (250, 500, 1000)         # phase B: small tenants (copies of golden_densmini) up to these totals
MINI = "golden_densmini"
MINI_LABELS = ("Service", "Datastore", "ExternalDependency", "Endpoint", "Table", "Transform", "Column", "KPI",
               "Dashboard", "Job", "FeatureFlag", "Deploy")
LEVELS = (1, 8, 32, 64)
DURATION_S = 15.0
WARMUP_S = 3.0
K = 1000                 # cross-tenant probes and own-graph controls
CMD_SAMPLE = 50          # tenants probed with each forbidden command
POOL = 48                # parameter sets per template
MAX_PROCS = 8            # client processes (threads fill the rest)
MEM_CEILING_MB = 2500.0  # projected engine used_memory after a step must stay at or below this
HOST_MIN_MB = 2000.0     # host MemAvailable that must remain beyond the projected growth
FIRST_MB = 15.0          # MB per product tenant assumed before anything is measured (the smoke run: ~14.3)
SMALL_FIRST_MB = 5.0     # MB per small tenant assumed before anything is measured
GATE_STEP = ("Q-GATE-1", "Q-GATE-3", "Q-BLAST-1")
TENANT_RE = re.compile(r"^dens\d{4}$")
GRAPH_FMT = "eval_{t}_bench"
COUNT_Q = "MATCH (n) RETURN count(n)"


# ------------------------------------------------------------------ pure helpers (unit-tested, no engine)
def tenant_id(i: int) -> str:
    return f"dens{i:04d}"


def graph_of(t: str) -> str:
    return GRAPH_FMT.format(t=t)


def pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile: the ceil(q·n)-th smallest (as evals/scale.py)."""
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[max(0, math.ceil(q * len(xs)) - 1)], 3)


def lat_stats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "p99": pct(xs, 0.99),
            "max": round(max(xs), 3) if xs else None, "mean": round(statistics.fmean(xs), 3) if xs else None}


def quantile_sketch(xs: list[float], points: int = 1000) -> list[float]:
    """The latency distribution as `points` nearest-rank quantiles (raw enough to redraw any percentile to 0.1 %)."""
    if not xs:
        return []
    xs = sorted(xs)
    return [round(xs[max(0, math.ceil(i / points * len(xs)) - 1)], 3) for i in range(1, points + 1)]


def step_allowed(used_mb: float, mb_per_tenant: float, new: int, host_avail_mb: float | None,
                 ceiling_mb: float = MEM_CEILING_MB, host_min_mb: float = HOST_MIN_MB) -> tuple[bool, str]:
    """The pre-registered memory guard for adding `new` tenants."""
    growth = 1.2 * mb_per_tenant * new
    if used_mb + growth > ceiling_mb:
        return False, (f"projected engine used_memory {used_mb + growth:.0f} MB (now {used_mb:.0f} + 1.2 x "
                       f"{mb_per_tenant:.2f} MB x {new}) exceeds the {ceiling_mb:.0f} MB ceiling")
    if host_avail_mb is not None and host_avail_mb - growth < host_min_mb:
        return False, (f"host MemAvailable {host_avail_mb:.0f} MB minus projected growth {growth:.0f} MB would leave "
                       f"less than {host_min_mb:.0f} MB")
    return True, ""


def ro_rule_tokens(template: str, tenant: str, password: str) -> list[str]:
    """The `ro_acme` line of deploy/users.acl.template, re-targeted to `tenant`: the same commands, the same key
    patterns with the tenant substituted, the password filled in. Fails loudly if the line changed shape."""
    line = next((ln.strip() for ln in template.splitlines() if re.match(r"user\s+ro_acme\s", ln.strip())), None)
    if line is None:
        raise ValueError("deploy/users.acl.template has no `user ro_acme` line")
    out = []
    for tok in line.split()[2:]:
        if tok == ">${FALKORDB_RO_PASSWORD}":
            out.append(">" + password)
        elif tok.startswith("~"):
            out.append(re.sub(r"(?<=_)acme(?=$|_|\*)", tenant, tok))
        else:
            out.append(tok)
    if any("acme" in t or "${" in t for t in out):
        raise ValueError("an acme key pattern or a template variable is left in the re-targeted rules")
    if not any(t == f"~eval_{tenant}_*" for t in out):
        raise ValueError("the ro_ rules no longer grant the tenant's eval_ key space the bench graphs live in")
    return out


def split_workers(m: int, max_procs: int = MAX_PROCS) -> list[int]:
    """Threads per client process: min(m, max_procs) processes, threads spread as evenly as possible."""
    p = max(1, min(m, max_procs))
    return [m // p + (1 if i < m % p else 0) for i in range(p)]


def error_class(e: BaseException) -> str:
    msg = str(e).lower()
    if "noperm" in msg or "no permissions" in msg:
        return "noperm"
    if "timed out" in msg or "timeout" in type(e).__name__.lower():
        return "timeout"
    if "max pending queries" in msg or "queue" in msg:
        return "queue_full"
    if "unreachable" in msg or "connection" in msg:
        return "connection"
    return "other"


def wilson_hi(k: int, n: int, z: float = 1.96) -> float | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(min(1.0, (c + h) / d), 4)


# ------------------------------------------------------------------ engine side
def _engine():
    from faultline.graph import client

    return client.engine()


def _info(section: str) -> dict:
    return _engine().connection.info(section)


def used_mb() -> float:
    return round(float(_info("memory")["used_memory"]) / 2**20, 2)


def rss_mb() -> float:
    return round(float(_info("memory")["used_memory_rss"]) / 2**20, 2)


def settled_used_mb(timeout_s: float = 20.0) -> float:
    """used_memory once asynchronous frees have finished (two readings 1 s apart within 1 MB)."""
    last, end = used_mb(), time.time() + timeout_s
    while time.time() < end:
        time.sleep(1.0)
        now = used_mb()
        if abs(now - last) < 1.0:
            return now
        last = now
    return last


def host_avail_mb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


def engine_cpu_s() -> float:
    c = _info("cpu")
    return float(c.get("used_cpu_user", 0)) + float(c.get("used_cpu_sys", 0))


def timed_copy(db, src: str, dst: str, deadline_s: float = 30.0) -> dict:
    """The same steps as graph/copy.copy_graph (GRAPH.COPY, wait for the ready flag, re-apply the schema, count the
    indexes, check ready), split so the raw GRAPH.COPY round trip is timed on its own."""
    from faultline.graph import writes
    from faultline.graph.errors import GraphNotReady

    t0 = time.perf_counter()
    db.select_graph(src).copy(dst)
    raw = (time.perf_counter() - t0) * 1000
    g = db.select_graph(dst)
    end = time.time() + deadline_s
    while time.time() < end:
        if g.ro_query("MATCH (m:Meta) RETURN m.ready LIMIT 1").result_set:
            break
        time.sleep(0.02)
    writes.apply_schema(g)
    g.ro_query("CALL db.indexes() YIELD label RETURN count(label)")
    ready = g.ro_query("MATCH (m:Meta) RETURN m.ready LIMIT 1").result_set
    if not ready or not ready[0][0]:
        raise GraphNotReady(f"copy {src} -> {dst} has no ready flag")
    return {"raw_ms": round(raw, 3), "ms": round((time.perf_counter() - t0) * 1000, 3)}


def bench_graphs(db) -> list[str]:
    return sorted(g for g in db.list_graphs() if re.fullmatch(r"eval_dens\d{4}_bench", g) or g == MINI)


def other_graphs(db) -> list[str]:
    """Graphs on the shared engine that are not the bench's (listed at step boundaries to flag concurrent work)."""
    return sorted(g for g in db.list_graphs() if not (re.fullmatch(r"eval_dens\d{4}_bench", g) or g == MINI))


def bench_users(db) -> list[str]:
    return sorted(u for u in db.connection.execute_command("ACL", "USERS")
                  if re.fullmatch(r"ro_dens\d{4}", u.decode() if isinstance(u, bytes) else u))


def cleanup(db) -> dict:
    users = bench_users(db)
    for u in users:
        db.connection.execute_command("ACL", "DELUSER", u)
    graphs = bench_graphs(db)
    for gname in graphs:
        db.select_graph(gname).delete()
    return {"users_deleted": len(users), "graphs_deleted": len(graphs), "users_left": len(bench_users(db)),
            "graphs_left": len(bench_graphs(db))}


# ------------------------------------------------------------------ 1. density
NODES_Q = ("MATCH (n:Node) WHERE any(l IN labels(n) WHERE l IN $labels) "
           "RETURN n.id, [x IN labels(n) WHERE x <> 'Node'][0], properties(n) ORDER BY n.id")
EDGES_Q = ("MATCH (a:Node)-[r]->(b:Node) WHERE any(l IN labels(a) WHERE l IN $labels) AND any(l IN labels(b) WHERE l IN "
           "$labels) RETURN a.id, b.id, type(r), properties(r), [x IN labels(a) WHERE x <> 'Node'][0], "
           "[x IN labels(b) WHERE x <> 'Node'][0] ORDER BY a.id, b.id, type(r)")


def build_mini(db) -> dict:
    """golden_densmini: golden_acme's failure-flow layer (MINI_LABELS nodes, every edge between them, their
    properties), written by the product's writers (graph/writes.py) with the full product schema and a ready flag."""
    from faultline.graph import writes

    t0 = time.perf_counter()
    src = db.select_graph(SRC)
    nodes = src.ro_query(NODES_Q, {"labels": list(MINI_LABELS)}, timeout=10_000).result_set
    edges = src.ro_query(EDGES_Q, {"labels": list(MINI_LABELS)}, timeout=10_000).result_set
    if MINI in set(db.list_graphs()):
        db.select_graph(MINI).delete()
    g = db.select_graph(MINI)
    W.ensure_key(db, MINI)
    writes.apply_schema(g)
    by_label: dict[str, list[dict]] = {}
    for i, lb, props in nodes:
        by_label.setdefault(lb, []).append({**{k: v for k, v in dict(props).items() if k != "embedding"}, "id": i})
    for lb, rows in sorted(by_label.items()):
        writes.upsert_nodes(g, lb, rows)
    by_type: dict[tuple, list[dict]] = {}
    for a, b, t, props, la, lb in edges:
        props = dict(props)
        if "k" in props:   # the writers' MERGE key
            props["key"] = props.pop("k")
        by_type.setdefault((t, la, lb), []).append({"src": a, "dst": b, "props": props})
    for (t, la, lb), rows in sorted(by_type.items()):
        writes.upsert_edges(g, t, la, lb, rows)
    writes.mark_ready(g, "m20-densmini", "bench", "densmini")
    st = g.ro_query("CALL db.meta.stats()")
    row = dict(zip([h[1] if isinstance(h, (list, tuple)) else h for h in st.header], st.result_set[0]))
    return {"graph": MINI, "nodes": int(row["nodeCount"]), "edges": int(row["relCount"]), "labels": list(MINI_LABELS),
            "build_s": round(time.perf_counter() - t0, 2)}


def _graph_size(db, name: str) -> dict:
    st = db.select_graph(name).ro_query("CALL db.meta.stats()")
    row = dict(zip([h[1] if isinstance(h, (list, tuple)) else h for h in st.header], st.result_set[0]))
    mem = db.connection.execute_command("GRAPH.MEMORY", "USAGE", name)
    return {"source": name, "nodes": int(row["nodeCount"]), "edges": int(row["relCount"]),
            "graph_memory_usage_mb": dict(zip(mem[::2], mem[1::2])).get("total_graph_sz_mb")}


def _phase(db, kind: str, src: str, first: int, targets: list[int], per0: float, out: dict, progress: bool) -> int:
    """Copy `src` into tenants first.. until each target total, step by step under the memory guard. Returns the
    last tenant index created."""
    base, rss0 = settled_used_mb(), rss_mb()
    others0 = other_graphs(db)
    n_kind, last = 0, first - 1
    per = per0
    copies: list[dict] = []
    for target in targets:
        new = target - last
        if new <= 0:
            continue
        ok, why = step_allowed(used_mb(), per, new, host_avail_mb())
        if not ok:
            out["stopped"].append({"kind": kind, "before_total": target, "reason": why})
            break
        t_step = time.perf_counter()
        step_copies = [{"tenant": tenant_id(i), "kind": kind, **timed_copy(db, src, graph_of(tenant_id(i)))}
                       for i in range(last + 1, target + 1)]
        copies += step_copies
        n_kind += new
        last = target
        now = settled_used_mb()
        per = (now - base) / n_kind
        others = other_graphs(db)
        out["steps"].append({"kind": kind, "n_total": last, "n_kind": n_kind, "used_mb": now, "rss_mb": rss_mb(),
                             "mb_per_tenant": round(per, 3), "host_avail_mb": host_avail_mb(),
                             "step_s": round(time.perf_counter() - t_step, 2),
                             "copy_ms": lat_stats([c["ms"] for c in step_copies]),
                             "concurrent_activity": others != others0,
                             **({"other_graphs_changed": sorted(set(others) ^ set(others0))[:20]} if others != others0 else {})})
        others0 = others
        if progress:
            print(f"[tenants] {kind}: {last} tenant graphs in all ({n_kind} of this kind): engine used {now:.0f} MB, "
                  f"{per:.2f} MB/tenant, copy p50 {out['steps'][-1]['copy_ms']['p50']} ms", file=sys.stderr, flush=True)
    out["kinds"][kind] = {"n": n_kind, "first": first, "last": last, "source": _graph_size(db, src),
                          "mb_per_tenant": round(per, 3) if n_kind else None,
                          "rss_mb_per_tenant": round((rss_mb() - rss0) / n_kind, 3) if n_kind else None,
                          "copy_ms": lat_stats([c["ms"] for c in copies]),
                          "copy_raw_ms": lat_stats([c["raw_ms"] for c in copies])}
    out["tenants"] += [(c["tenant"], kind) for c in copies]
    return last


def density(db, steps: list[int], total_steps: list[int], progress: bool) -> dict:
    out: dict = {"steps": [], "stopped": [], "kinds": {}, "tenants": []}
    out["used_mb_before"], out["rss_mb_before"] = settled_used_mb(), rss_mb()
    out["other_graphs_before"] = len(other_graphs(db))
    last = _phase(db, "product", SRC, 1, steps, FIRST_MB, out, progress)
    if total_steps:   # phase B runs whether or not phase A was stopped by the guard
        out["mini_build"] = build_mini(db)
        _phase(db, "small", MINI, last + 1, total_steps, SMALL_FIRST_MB, out, progress)
    out["n"] = len(out["tenants"])
    out["used_mb_at_n"] = settled_used_mb()
    out["rss_mb_at_n"] = rss_mb()
    out["host_avail_mb_at_n"] = host_avail_mb()
    return out


# ------------------------------------------------------------------ 2. isolation
def isolation(db, tenants: list[str], password: str, k: int, cmd_sample: int, nodes: dict[str, int],
              rnd: random.Random, progress: bool) -> dict:
    """`nodes`: tenant → the node count its own graph must show (its kind's source graph)."""
    import redis

    from faultline.config import settings
    from faultline.graph.ro import RO

    template = (ROOT / "deploy" / "users.acl.template").read_text()
    t0 = time.perf_counter()
    for t in tenants:
        db.connection.execute_command("ACL", "SETUSER", f"ro_{t}", "reset", *ro_rule_tokens(template, t, password))
    out: dict = {"users": len(tenants), "acl_setuser_s": round(time.perf_counter() - t0, 2)}
    conns: dict[str, redis.Redis] = {}

    def conn(t: str) -> redis.Redis:
        if t not in conns:
            conns[t] = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port, username=f"ro_{t}",
                                   password=password, socket_timeout=10, single_connection_client=True)
        return conns[t]

    pairs = []
    while len(pairs) < k:
        a, b = rnd.sample(tenants, 2) if len(tenants) > 1 else (tenants[0], tenants[0])
        if a != b:
            pairs.append((a, b))
    cross = {"probes": 0, "denied": 0, "leaks": 0, "other_errors": 0, "examples": []}
    own = {"probes": 0, "ok": 0, "wrong_count": 0, "errors": 0}
    app = {"probes": 0, "refused": 0, "reached_engine": 0}
    try:
        for a, b in pairs:
            cross["probes"] += 1
            try:
                r = conn(a).execute_command("GRAPH.RO_QUERY", graph_of(b), COUNT_Q)
                cross["leaks"] += 1
                cross["examples"].append({"user": f"ro_{a}", "graph": graph_of(b), "reply_rows": len(r[1]) if r else None})
            except redis.exceptions.NoPermissionError:
                cross["denied"] += 1
            except Exception as e:  # noqa: BLE001 - recorded: not a leak, not a clean denial
                cross["other_errors"] += 1
                if len(cross["examples"]) < 5:
                    cross["examples"].append({"user": f"ro_{a}", "graph": graph_of(b), "error": str(e)[:160]})
            own["probes"] += 1
            try:
                r = conn(a).execute_command("GRAPH.RO_QUERY", graph_of(a), COUNT_Q)
                if int(r[1][0][0]) == nodes[a]:
                    own["ok"] += 1
                else:
                    own["wrong_count"] += 1
            except Exception:  # noqa: BLE001 - counted
                own["errors"] += 1
            app["probes"] += 1
            try:
                RO(a, graph_of(b))
                app["reached_engine"] += 1
            except ValueError:
                app["refused"] += 1
        cmds = {
            "GRAPH.QUERY write": lambda c, t: c.execute_command("GRAPH.QUERY", graph_of(t), "CREATE (:Leak {at: 1})"),
            "GRAPH.DELETE": lambda c, t: c.execute_command("GRAPH.DELETE", graph_of(t)),
            "GRAPH.COPY": lambda c, t: c.execute_command("GRAPH.COPY", graph_of(t), graph_of(t) + "_copy"),
            "GRAPH.LIST": lambda c, t: c.execute_command("GRAPH.LIST"),
            "GRAPH.PROFILE": lambda c, t: c.execute_command("GRAPH.PROFILE", graph_of(t), COUNT_Q),
            # the current value, so even an unexpected success changes nothing
            "GRAPH.CONFIG SET": lambda c, t: c.execute_command("GRAPH.CONFIG", "SET", "TIMEOUT_DEFAULT", _timeout_default(db)),
        }
        sample = sorted(rnd.sample(tenants, min(cmd_sample, len(tenants))))
        forbidden = {name: {"probes": 0, "denied": 0, "allowed": 0, "other_errors": 0} for name in cmds}
        for t in sample:
            for name, fn in cmds.items():
                f = forbidden[name]
                f["probes"] += 1
                try:
                    fn(conn(t), t)
                    f["allowed"] += 1
                except redis.exceptions.NoPermissionError:
                    f["denied"] += 1
                except Exception:  # noqa: BLE001 - counted
                    f["other_errors"] += 1
        intact = 0
        for t in sample:
            try:
                intact += int(db.select_graph(graph_of(t)).ro_query(COUNT_Q).result_set[0][0]) == nodes[t]
            except Exception:  # noqa: BLE001 - a missing graph (an unexpectedly allowed DELETE) is not intact
                pass
    finally:
        for c in conns.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001 - closing a probe connection
                pass
    out.update({"cross_tenant": cross, "own_graph": own, "app_layer": app, "forbidden": forbidden,
                "forbidden_probes": sum(f["probes"] for f in forbidden.values()),
                "forbidden_denied": sum(f["denied"] for f in forbidden.values()),
                "forbidden_allowed": sum(f["allowed"] for f in forbidden.values()),
                "sample_graphs_intact": intact, "sample": len(sample),
                "leak_rate_ci_hi": wilson_hi(cross["leaks"], cross["probes"])})
    if progress:
        print(f"[tenants] isolation: {cross['denied']}/{cross['probes']} cross-tenant reads denied, {cross['leaks']} "
              f"leaks; own-graph reads {own['ok']}/{own['probes']}; forbidden {out['forbidden_denied']}/"
              f"{out['forbidden_probes']} denied", file=sys.stderr, flush=True)
    return out


def _timeout_default(db) -> int:
    return int(db.connection.execute_command("GRAPH.CONFIG", "GET", "TIMEOUT_DEFAULT")[1])


# ------------------------------------------------------------------ 3. concurrency
def param_pool(rnd: random.Random, n: int = POOL) -> tuple[dict[str, list[dict]], dict]:
    """Gate-step parameters drawn from golden_acme itself (read once, engine connection): deploy → service pairs for
    Q-GATE-1 (with and without a causal path), the deploy's component → service for Q-GATE-3, components for
    Q-BLAST-1. Which pairs have a path is read with Q-GATE-1 on golden_acme (the product's RO wrapper)."""
    from faultline.graph.ro import RO

    g = _engine().select_graph(SRC)
    deploys = [tuple(r) for r in g.ro_query("MATCH (d:Deploy)-[:CHANGED]->(c) RETURN d.id, c.id ORDER BY d.id").result_set]
    services = [r[0] for r in g.ro_query("MATCH (s:Service) RETURN s.id ORDER BY s.id").result_set]
    if not deploys or not services:
        raise RuntimeError(f"{SRC} has no deploys or services; run `make seed`")
    ro = RO("acme", SRC)
    gate1, gate3, blast, with_path, same = [], [], [], 0, 0
    while len(gate1) < n:
        d, c = rnd.choice(deploys)
        s = rnd.choice(services)
        if c == s:   # algo.maxFlow refuses a source that is the sink; the gate never asks that (amendment about 21:30 IST)
            same += 1
            continue
        gate1.append({"cause": d, "symptom": s})
        gate3.append({"sources": [c], "symptom": s})
        blast.append({"id": c})
        with_path += 1 if ro.run("Q-GATE-1", gate1[-1]).rows else 0
    return ({"Q-GATE-1": gate1, "Q-GATE-3": gate3, "Q-BLAST-1": blast},
            {"per_template": n, "gate1_with_path": with_path, "deploys": len(deploys), "services": len(services),
             "redrawn_component_is_symptom": same})


def _worker(idx: int, threads: int, tenants: list[str], pool: dict, warmup: float, duration: float, seed: int,
            ready_q, go, out_q) -> None:
    """One client process: per-tenant RO pools warmed (one Q-META-1 per tenant), then `threads` investigators."""
    import resource
    import threading

    from faultline.graph.ro import RO

    try:
        for t in tenants:
            RO(t, graph_of(t)).run("Q-META-1", {})
    except Exception as e:  # noqa: BLE001 - reported to the parent, which fails loudly
        ready_q.put({"idx": idx, "error": f"warm-up failed: {type(e).__name__}: {str(e)[:200]}"})
        return
    ready_q.put({"idx": idx, "ok": True})
    go.wait()
    t_go = time.perf_counter()
    w0, w1 = t_go + warmup, t_go + warmup + duration
    lat: dict[str, list[float]] = {tid: [] for tid in GATE_STEP}
    errs: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    steps = [0]
    lock = threading.Lock()
    cpu: dict[str, float] = {}

    def run(j: int) -> None:
        rnd = random.Random(seed * 1000 + idx * 100 + j)
        mine: dict[str, list[float]] = {tid: [] for tid in GATE_STEP}
        my_err: dict[str, int] = {}
        n_steps = 0
        while True:
            now = time.perf_counter()
            if now >= w1:
                break
            t = rnd.choice(tenants)
            in_window = now >= w0
            for tid in GATE_STEP:
                t0 = time.perf_counter()
                try:
                    RO(t, graph_of(t)).run(tid, rnd.choice(pool[tid]))
                    ok = True
                except Exception as e:  # noqa: BLE001 - an error is a measurement, never dropped
                    ok = False
                    if t0 >= w0:
                        c = error_class(e)
                        my_err[c] = my_err.get(c, 0) + 1
                        with lock:
                            if len(examples.setdefault(c, [])) < 3:
                                examples[c].append(f"{tid}: {type(e).__name__}: {str(e)[:160]}")
                if ok and t0 >= w0 and t0 < w1:
                    mine[tid].append((time.perf_counter() - t0) * 1000)
            if in_window:
                n_steps += 1
        with lock:
            for tid in GATE_STEP:
                lat[tid].extend(mine[tid])
            for c, v in my_err.items():
                errs[c] = errs.get(c, 0) + v
            steps[0] += n_steps

    def cpu_mark(key: str, at: float) -> None:
        time.sleep(max(0.0, at - time.perf_counter()))
        r = resource.getrusage(resource.RUSAGE_SELF)
        cpu[key] = r.ru_utime + r.ru_stime

    ths = [threading.Thread(target=run, args=(j,)) for j in range(threads)]
    marks = [threading.Thread(target=cpu_mark, args=("w0", w0)), threading.Thread(target=cpu_mark, args=("w1", w1))]
    for th in ths + marks:
        th.start()
    for th in ths + marks:
        th.join()
    out_q.put({"idx": idx, "threads": threads, "lat": lat, "errors": errs, "examples": examples, "steps": steps[0],
               "cpu_cores": round((cpu.get("w1", 0) - cpu.get("w0", 0)) / duration, 3)})


def concurrency(tenants: list[str], password: str, levels: list[int], pool: dict, warmup: float, duration: float,
                progress: bool) -> list[dict]:
    ctx = mp.get_context("spawn")
    os.environ["FALKORDB_RO_PASSWORD"] = password   # inherited by the spawned workers only for this phase
    rows = []
    try:
        for m in levels:
            split = split_workers(m)
            ready_q, out_q, go = ctx.Queue(), ctx.Queue(), ctx.Event()
            procs = [ctx.Process(target=_worker, args=(i, th, tenants, pool, warmup, duration, SEED + m, ready_q, go,
                                                       out_q), daemon=True) for i, th in enumerate(split)]
            for p in procs:
                p.start()
            try:
                for _ in procs:
                    msg = ready_q.get(timeout=600)
                    if msg.get("error"):
                        raise RuntimeError(f"client process {msg['idx']}: {msg['error']}")
                go.set()
                t_go = time.perf_counter()
                time.sleep(warmup)
                c0, u0 = engine_cpu_s(), time.perf_counter()
                time.sleep(max(0.0, t_go + warmup + duration - time.perf_counter()))
                c1, u1 = engine_cpu_s(), time.perf_counter()
                parts = [out_q.get(timeout=duration + warmup + 120) for _ in procs]
            finally:
                for p in procs:
                    p.join(timeout=30)
                    if p.is_alive():
                        p.kill()   # our own child, by its handle (never a pattern)
            lat = {tid: [x for part in parts for x in part["lat"][tid]] for tid in GATE_STEP}
            allx = [x for tid in GATE_STEP for x in lat[tid]]
            errs: dict[str, int] = {}
            for part in parts:
                for c, v in part["errors"].items():
                    errs[c] = errs.get(c, 0) + v
            row = {"investigators": m, "processes": len(split), "threads": split, "duration_s": duration,
                   "warmup_s": warmup, "queries": len(allx), "steps": sum(p["steps"] for p in parts),
                   "qps": round(len(allx) / duration, 1), "steps_per_s": round(sum(p["steps"] for p in parts) / duration, 1),
                   "latency_ms": lat_stats(allx), "per_template": {tid: lat_stats(lat[tid]) for tid in GATE_STEP},
                   "errors": errs, "error_total": sum(errs.values()),
                   "error_examples": {c: [m for p in parts for m in p.get("examples", {}).get(c, [])][:3] for c in errs},
                   "engine_cpu_cores": round((c1 - c0) / (u1 - u0), 2),
                   "client_cpu_cores_max": max(p["cpu_cores"] for p in parts),
                   "client_cpu_cores_total": round(sum(p["cpu_cores"] for p in parts), 2),
                   "sketch_ms": quantile_sketch(allx)}
            rows.append(row)
            if progress:
                lm = row["latency_ms"]
                print(f"[tenants] {m:>2} investigators: {row['qps']} queries/s, p50 {lm['p50']} / p95 {lm['p95']} / "
                      f"p99 {lm['p99']} ms, errors {row['error_total']}, engine {row['engine_cpu_cores']} cores, "
                      f"client max {row['client_cpu_cores_max']} cores/process", file=sys.stderr, flush=True)
    finally:
        os.environ.pop("FALKORDB_RO_PASSWORD", None)
    return rows


# ------------------------------------------------------------------ the run
def engine_config(db) -> dict:
    out = {}
    for k in ("THREAD_COUNT", "MAX_QUEUED_QUERIES", "TIMEOUT_MAX", "TIMEOUT_DEFAULT", "QUERY_MEM_CAPACITY", "CACHE_SIZE"):
        try:
            out[k] = db.connection.execute_command("GRAPH.CONFIG", "GET", k)[1]
        except Exception as e:  # noqa: BLE001 - a key this engine lacks
            out[k] = f"n/a: {str(e)[:60]}"
    out["maxmemory_mb"] = round(float(_info("memory").get("maxmemory", 0)) / 2**20, 1)
    return out


def run(steps: list[int], levels: list[int], k: int, cmd_sample: int, warmup: float, duration: float, reason: str,
        progress: bool = True, total_steps: list[int] | None = None) -> dict:
    from faultline.graph.algo import registry

    db = _engine()
    if SRC not in set(db.list_graphs()):
        raise SystemExit(f"{SRC} does not exist; run `make seed`")
    meta = registry.resolved_meta()
    out: dict = {"bench": "tenants", "engine": meta.get("engine"), "digest": meta.get("digest"), "seed": SEED,
                 "reason": reason, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "machine": {"cpus": os.cpu_count(), "host_avail_mb": host_avail_mb()},
                 "config": engine_config(db), "steps_planned": {"product": steps, "small_totals": total_steps or []},
                 "levels": levels}
    stale = cleanup(db)   # a crashed earlier run's leftovers (bench-owned names only)
    if stale["users_deleted"] or stale["graphs_deleted"]:
        out["stale_cleaned"] = stale
    rnd = random.Random(SEED)
    password = secrets.token_urlsafe(32)
    try:
        out["density"] = density(db, steps, list(total_steps or []), progress)
        n = out["density"]["n"]
        if not n:
            raise SystemExit("no tenant step fitted under the memory guard: " + str(out["density"]["stopped"]))
        kinds = out["density"]["kinds"]
        tenants = [t for t, _ in out["density"]["tenants"]]
        expect = {t: kinds[kind]["source"]["nodes"] for t, kind in out["density"]["tenants"]}
        out["isolation"] = isolation(db, tenants, password, k, cmd_sample, expect, rnd, progress)
        pool, pinfo = param_pool(rnd)
        out["params"] = pinfo
        out["concurrency"] = concurrency(tenants, password, levels, pool, warmup, duration, progress)
        out["used_mb_peak_observed"] = used_mb()
    finally:
        out["cleanup"] = cleanup(db)
        out["used_mb_after_cleanup"] = settled_used_mb()
        out["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--steps", default=",".join(map(str, STEPS)), help="phase A totals (product tenants)")
    ap.add_argument("--total-steps", default=",".join(map(str, TOTAL_STEPS)),
                    help="phase B totals (small tenants added up to these; empty = none)")
    ap.add_argument("--levels", default=",".join(map(str, LEVELS)))
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--cmd-sample", type=int, default=CMD_SAMPLE)
    ap.add_argument("--warmup", type=float, default=WARMUP_S)
    ap.add_argument("--duration", type=float, default=DURATION_S)
    ap.add_argument("--reason", default="M20 Wave B pre-registered run (PREREGISTRATION addendum 2026-10-17 21:10 IST)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    steps = sorted(int(x) for x in a.steps.split(",") if x.strip())
    levels = [int(x) for x in a.levels.split(",") if x.strip()]
    total_steps = sorted(int(x) for x in a.total_steps.split(",") if x.strip())
    out = run(steps, levels, a.k, a.cmd_sample, a.warmup, a.duration, a.reason, not a.quiet, total_steps)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2, default=str) + "\n")
    d, iso = out["density"], out["isolation"]
    for kind, x in d["kinds"].items():
        print(f"{kind}: {x['n']} tenants, {x['mb_per_tenant']} MB each, copy p50 {x['copy_ms']['p50']} ms")
    print(f"{d['n']} tenants in all; leaks {iso['cross_tenant']['leaks']}/{iso['cross_tenant']['probes']}; cleanup "
          f"{out['cleanup']}")
    for r in out["concurrency"]:
        print(f"  {r['investigators']:>2} investigators: {r['qps']} q/s, p99 {r['latency_ms']['p99']} ms, "
              f"errors {r['error_total']}")
    print(f"wrote {a.out}")
    clean = out["cleanup"]["users_left"] == 0 and out["cleanup"]["graphs_left"] == 0
    return 0 if clean and iso["cross_tenant"]["leaks"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
