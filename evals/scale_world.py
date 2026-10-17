"""Deterministic synthetic scale tenants for the scale benchmark (M14 #5, `make scale`).

A scale tenant is a FEDERATION of globex units: unit u is exactly what the existing globex generators produce for
seed 42 + u (`ingest/globex/*`: 200 services in 12 domains, 180 people, 120 days of commits/PRs/deploys, 150 past
incidents, ADRs, runbooks, SLOs, customers, committed vectors), so lineage and history grow in proportion with the
service count and nothing here is a new world model. Ids are namespaced per unit (unit 0 keeps globex's own ids,
unit u > 0 gets the suffix `-uNNN`; File ids and paths get a `uNNN/` directory so the preflight's `file:<path>`
convention still holds), and every `tenant` property is the scale tenant's id.

What makes the units ONE company rather than U disjoint copies: unit 0's platform domains (identity, insights,
infra) are the GLOBAL platform. Every other unit's platform anchors front the global anchor of the same name
(`auth-service-u007` CALLS `auth-service`), with the globex spec's callee criticality (`callee_caps`; synchronous
1.0 otherwise) and 20% of the regional anchor's inbound traffic. The global anchors therefore become hubs whose
fan-in grows with the tenant: the shape where graph algorithms are stressed. The federation edges only go from a unit
to unit 0's platform, and unit 0's platform never calls into another unit, so the failure-flow graph stays acyclic.

Graphs: `golden_scale<k>` (seeded here through the same bundle → UNWIND MERGE writers as `scripts/seed.py`) and
`eval_scale<k>_*` clean rooms. Tenant ids `scale1k` / `scale10k` / `scale50k` pass `graph/tenant.py` and can never
collide with acme or globex. No scenario literal and no ground truth lives here: the world config below is the
system under observation, and `evals/scale.py` (the grader side) decides expectations from it, never from FalkorDB.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.agent.weights import tier_weight, weights  # noqa: E402
from faultline.ingest.bundle import Bundle  # noqa: E402
from faultline.ingest.globex import docs, embeddings, history, load_spec, obligations, org, topology  # noqa: E402
from faultline.ingest.lineage_to_graph import flow  # noqa: E402

BASE_SEED = 42                       # unit 0 = globex itself (seed 42)
UNIT_PRODUCERS = (topology, org, obligations, history, docs, embeddings)   # scripts/seed.py PRODUCERS["globex"] order
SIZES = {"1k": 1_000, "3k": 3_000, "5k": 5_000, "10k": 10_000, "25k": 25_000, "50k": 50_000}   # 3k/5k: M20 curve
FED_SHARE = 0.2                       # share of a regional platform anchor's inbound traffic sent to the global one
FED_WHY = "regional platform front calls the global platform service synchronously"
# text and team-key properties are never namespaced, even when a value happens to equal a node id
NO_NS_PROPS = {"name", "title", "summary", "note", "route", "url", "cap_why", "explanation", "doc", "text", "body",
               "path", "embedding_model", "protocol", "kind", "lang", "role", "state", "metric", "domain", "key",
               "team_id"}


def tenant_for(label: str) -> str:
    if label not in SIZES:
        raise ValueError(f"unknown scale size {label!r} (one of {', '.join(SIZES)})")
    return f"scale{label}"


def unit_services() -> int:
    return int(load_spec()["services_total"])


def n_units(services: int) -> int:
    return max(1, round(int(services) / unit_services()))


def suffix(u: int) -> str:
    return "" if u == 0 else f"-u{u:03d}"


def ns(id_: str, u: int) -> str:
    """The unit-namespaced id (unit 0 keeps globex's ids)."""
    if u == 0:
        return id_
    if id_.startswith("file:"):
        return f"file:u{u:03d}/{id_.removeprefix('file:')}"
    return id_ + suffix(u)


def unit_seed(u: int) -> int:
    return BASE_SEED + u


def platform_anchors() -> list[str]:
    return [a["id"] for d in load_spec()["domains"] if d.get("platform") for a in d["anchors"]]


# ------------------------------------------------------------------ bundles
def _ns_value(v: Any, u: int, ids: set[str]) -> Any:
    if isinstance(v, str) and v in ids:
        return ns(v, u)
    if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
        return [ns(x, u) if x in ids else x for x in v]
    return v


def _ns_props(props: dict[str, Any], u: int, ids: set[str], tenant: str) -> dict[str, Any]:
    out = {}
    for k, v in props.items():
        if k == "tenant":
            out[k] = tenant
        elif k == "path" and u and isinstance(v, str) and props.get("repo_id") is not None:   # File.path ↔ File id
            out[k] = f"u{u:03d}/{v}"
        elif k in NO_NS_PROPS or k == "embedding":
            out[k] = v
        else:
            out[k] = _ns_value(v, u, ids)
    return out


def unit_bundle(u: int, tenant: str) -> Bundle:
    """Unit u: the globex producers for seed 42 + u, namespaced into the scale tenant."""
    raw = Bundle()
    for m in UNIT_PRODUCERS:
        raw.merge(m.build(unit_seed(u)))
    ids = {r["id"] for rows in raw.nodes.values() for r in rows}
    b = Bundle()
    for label, rows in raw.nodes.items():
        for r in rows:
            b.nodes[label].append({"id": ns(r["id"], u), **_ns_props({k: v for k, v in r.items() if k != "id"}, u, ids, tenant)})
    for key, rows in raw.edges.items():
        for e in rows:
            b.edges[key].append({"src": ns(e["src"], u), "dst": ns(e["dst"], u), "props": _ns_props(e["props"], u, ids, tenant)})
    return b


def _inbound(t: topology.Topology) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in t.calls:
        out[c.server] = out.get(c.server, 0) + c.rps
    return out


def federation_calls(u: int) -> list[topology.Call]:
    """Unit u's platform anchors → the global (unit 0) anchor of the same name. Empty for unit 0."""
    if u == 0:
        return []
    spec, t = load_spec(), topology.generate(unit_seed(u))
    inbound = _inbound(t)
    out = []
    for a in platform_anchors():
        cc = spec["callee_caps"].get(a)
        cap, why = (float(cc["cap"]), cc["why"]) if cc is not None else (1.0, FED_WHY)
        out.append(topology.Call(ns(a, u), a, max(1, round(FED_SHARE * inbound.get(a, 0))), cap, why))
    return out


def federation_bundle(u: int, tenant: str) -> Bundle:  # noqa: ARG001 - tenant kept for a uniform producer signature
    entry_rps = float(weights()["impact"]["entry_rps"])
    tier = topology.generate(unit_seed(u)).tier
    b = Bundle()
    for c in federation_calls(u):
        local = c.client.removesuffix(suffix(u))
        b.edge("CALLS", "Service", c.client, "Service", c.server, rps=c.rps, err_rate=0.0, p99_ms=0.0)
        if c.cap > 0:
            flow(b, "Service", c.server, "Service", c.client, c.cap, (c.rps / entry_rps) * tier_weight(tier[local]),
                 "service", rps=c.rps, via_endpoint="", cap_why=c.why)
    return b


def bundles(services: int, tenant: str) -> Iterator[tuple[str, Bundle]]:
    """Unit bundles, then the federation edges (their endpoints exist by then). Streamed: one unit in memory at a time."""
    U = n_units(services)
    for u in range(U):
        yield f"unit{u}", unit_bundle(u, tenant)
    fed = Bundle()
    for u in range(1, U):
        fed.merge(federation_bundle(u, tenant))
    yield "federation", fed


def bundle_hash(b: Bundle) -> str:
    canon = json.dumps({"nodes": {k: sorted(v, key=lambda r: r["id"]) for k, v in b.nodes.items()},
                        "edges": {"|".join(k): v for k, v in sorted(b.edges.items())}},
                       sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


# ------------------------------------------------------------------ seeding (same writers as scripts/seed.py)
def ensure_key(db, name: str) -> None:
    """Create graph `name` (no nodes) when it does not exist yet, so `writes.apply_schema` can read its indexes first.
    On 2026-10-17 apply_schema briefly failed on a missing key ("Invalid graph operation on empty key"; since fixed in
    writes.py). An empty projection write creates the key and nothing else, so this guard is harmless either way."""
    from faultline.graph import writes

    if name not in set(db.list_graphs()):
        writes.build_scratch(db.select_graph(name), nodes=[], edges=[])


def seed(services: int, tenant: str, graph: str, progress: bool = False) -> dict:
    """Seed `graph` from scratch: schema, every unit bundle (UNWIND … MERGE batches via graph/writes), federation edges,
    normalised flow props, the Intent constraint, seed-time LEARN (derived runbooks), then the ready flag. Returns timings
    (generation vs writes are separated) and counts."""
    from faultline.graph import client, copy as gcopy, writes
    from faultline.graph.algo import registry
    from faultline.memory.learn import consolidate_all

    db = client.engine()
    gcopy.delete_if_exists(db, graph)
    g = db.select_graph(graph)
    t0 = time.perf_counter()
    ensure_key(db, graph)
    writes.apply_schema(g)
    gen_s = write_s = 0.0
    nodes = edges = 0
    h = hashlib.sha256()
    it = bundles(services, tenant)
    while True:
        t1 = time.perf_counter()
        nxt = next(it, None)          # generation (pure Python, no FalkorDB)
        if nxt is None:
            break
        name, b = nxt
        h.update(bundle_hash(b).encode())
        t2 = time.perf_counter()
        gen_s += t2 - t1
        for label in sorted(b.nodes):
            rows = b.nodes[label]
            writes.upsert_nodes(g, label, rows)
            vecs = [r for r in rows if "embedding" in r]
            if vecs:
                writes.set_vectors(g, label, vecs)
            nodes += len(rows)
        for key in sorted(b.edges):
            writes.upsert_edges(g, key[0], key[1], key[2], b.edges[key])
            edges += len(b.edges[key])
        write_s += time.perf_counter() - t2
        if progress:
            print(f"  {graph}: {name} written ({nodes} node rows, {edges} edge rows so far)", file=sys.stderr, flush=True)
    t2 = time.perf_counter()
    writes.normalise_flow_props(g)
    writes.ensure_constraints(g)
    t3 = time.perf_counter()
    derived = consolidate_all(tenant, graph)
    t4 = time.perf_counter()
    writes.mark_ready(g, h.hexdigest(), registry.resolved_meta().get("engine") or "?", tenant)
    return {"graph": graph, "units": n_units(services), "data_hash": h.hexdigest()[:12], "node_rows": nodes,
            "edge_rows": edges, "generate_s": round(gen_s, 2), "write_s": round(write_s, 2),
            "finalise_s": round(t3 - t2, 2), "learn_s": round(t4 - t3, 2), "derived_runbooks": len(derived),
            "seed_s": round(time.perf_counter() - t0, 2)}


# ------------------------------------------------------------------ the world (config) for the grader and telemetry
@dataclass
class World:
    """The scale tenant's call graph as configured (never read from FalkorDB): what the world simulator and the
    benchmark's expectations are computed from, like evals/gate_bench.py's Topo over the acme config."""
    services: int
    units: int
    label: dict[str, str] = field(default_factory=dict)          # component id -> Service | Datastore | ExternalDependency
    unit_of: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[str, str, int, float]] = field(default_factory=list)   # (client, server, rps, cap)
    fail_out: dict[str, list[tuple[str, float]]] = field(default_factory=dict)   # server -> [(client, cap)] cap > 0
    fail_in: dict[str, list[tuple[str, float, float]]] = field(default_factory=dict)  # client -> [(server, cap, share)]
    deps: dict[str, list[str]] = field(default_factory=dict)      # client -> servers it depends on (cap > 0)

    def components(self) -> list[str]:
        return sorted(n for n, lb in self.label.items() if lb in ("Service", "Datastore"))

    def reach(self, start: str, sync_only: bool = False) -> set[str]:
        """Components a failure at `start` can reach over the configured failure edges (grader-side oracle)."""
        seen: set[str] = set()
        stack = [start]
        while stack:
            x = stack.pop()
            for y, cap in self.fail_out.get(x, ()):
                if (cap >= 1.0 or not sync_only) and y not in seen and y != start:
                    seen.add(y)
                    stack.append(y)
        return seen

    def upstream(self, start: str, max_hops: int) -> dict[str, int]:
        """Dependencies of `start` within max_hops (hop distance), over cap > 0 calls."""
        out: dict[str, int] = {}
        frontier = [start]
        for h in range(1, max_hops + 1):
            nxt = []
            for x in frontier:
                for y in self.deps.get(x, ()):
                    if y not in out and y != start:
                        out[y] = h
                        nxt.append(y)
            frontier = nxt
        return out


@lru_cache(maxsize=3)
def world(services: int) -> World:
    U = n_units(services)
    w = World(services, U)
    for u in range(U):
        t = topology.generate(unit_seed(u))
        for k, lb in t.label.items():
            w.label[ns(k, u)] = lb
            w.unit_of[ns(k, u)] = u
        w.calls += [(ns(c.client, u), ns(c.server, u), c.rps, c.cap) for c in t.calls]
        w.calls += [(c.client, c.server, c.rps, c.cap) for c in federation_calls(u)]
    inbound: dict[str, int] = {}
    for cl, sv, rps, _ in w.calls:
        inbound[cl] = inbound.get(cl, 0)
        inbound[sv] = inbound.get(sv, 0) + rps
    for cl, sv, rps, cap in w.calls:
        if cap <= 0:
            continue
        share = min(1.0, rps / (inbound.get(cl) or 1))     # Q-SIM-1's call share (in_rps 0 → 1, as the simulator)
        w.fail_out.setdefault(sv, []).append((cl, cap))
        w.fail_in.setdefault(cl, []).append((sv, cap, share))
        w.deps.setdefault(cl, []).append(sv)
    return w


__all__ = ["SIZES", "tenant_for", "n_units", "ns", "unit_bundle", "federation_bundle", "bundles", "seed", "world", "World"]
