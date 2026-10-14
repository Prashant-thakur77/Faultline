"""globex service domain → Bundle (same conventions as `ingest/otel_topology.py`).

Generation (deterministic, seed 42):
1. Services: each domain's anchors (spec) plus `<prefix>-<stem>` services up to its quota (200 in total).
2. Order: domains in spec order, anchors first, then datastores and external dependencies. A call always goes
   from a node earlier in that order to a later one (a DAG); the event-bus deliveries in the spec are the only
   exception, and every consumer sits after every publisher, so the graph stays acyclic by construction.
3. Backbone calls from the spec, then preferential attachment: walking the order backwards, every service picks
   1–4 servers among later nodes with weight (in-degree + 1) × locality (same domain ≫ platform ≫ other), so
   shared platform services become hubs (meaningful betweenness). Non-batch services left without a caller get
   one from their own domain (or the storefront BFF).
4. cap = criticality (spec `callee_caps`, else a sync / best-effort / async mix with a reason); rps = traffic
   matrix pushed down the order from the entry (entry_rps), batch roles generate their own small load.

Bundle: Service {name, lang, tier, revenue_path, status, entry, domain}, Datastore, ExternalDependency, Endpoint,
FeatureFlag {state, cuts_src, cuts_dst}; CALLS {rps}; PROPAGATES_TO/DEPENDS_ON via `lineage_to_graph.flow`
(cap, w, cut_cost = rps / entry_rps × tier weight of the client, domain 'service'); EXPOSES; GATES.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ...agent.weights import tier_weight, weights
from ..bundle import Bundle
from ..lineage_to_graph import flow
from . import TENANT, load_spec

SEED_SALT = 7919


@dataclass(frozen=True)
class Call:
    client: str
    server: str
    rps: int
    cap: float
    why: str = ""


@dataclass
class Topology:
    entry: str
    services: list[dict[str, Any]]
    datastores: list[dict[str, Any]]
    externals: list[dict[str, Any]]
    calls: list[Call]
    endpoints: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    label: dict[str, str] = field(default_factory=dict)    # id -> Service | Datastore | ExternalDependency
    domain: dict[str, str] = field(default_factory=dict)   # component id -> domain (team) key it was built in
    tier: dict[str, int] = field(default_factory=dict)

    def components(self) -> dict[str, str]:
        """Owned, deployable components (services and datastores; externals are not ours)."""
        return {k: v for k, v in self.label.items() if v in ("Service", "Datastore")}


def _quotas(spec: dict) -> dict[str, int]:
    doms = spec["domains"]
    total = int(spec["services_total"])
    base, extra = divmod(total, len(doms))
    q = {d["key"]: base + (1 if i < extra else 0) for i, d in enumerate(doms)}
    for d in doms:
        if len(d["anchors"]) > q[d["key"]]:
            raise ValueError(f"domain {d['key']}: more anchors than its quota")
    return q


def _services(spec: dict, rng: random.Random) -> list[dict[str, Any]]:
    quotas = _quotas(spec)
    batch = set(spec["batch_stems"])
    out: list[dict[str, Any]] = []
    for d in spec["domains"]:
        for a in d["anchors"]:
            out.append({"id": a["id"], "name": a["name"], "lang": rng.choice(d["langs"]), "tier": int(a["tier"]),
                        "revenue_path": bool(a["revenue_path"]), "domain": d["key"], "anchor": True, "batch": False})
        taken = {s["id"] for s in out}
        stems = [s for s in rng.sample(spec["stems"], len(spec["stems"])) if f"{d['prefix']}-{s}" not in taken]
        need = quotas[d["key"]] - len(d["anchors"])
        if need > len(stems):
            raise ValueError(f"domain {d['key']}: not enough stems for its quota")
        for stem in stems[:need]:
            revenue = bool(d.get("revenue")) and rng.random() < 0.12
            out.append({"id": f"{d['prefix']}-{stem}", "name": f"{d['name'].lower()} {stem.replace('-', ' ')}",
                        "lang": rng.choice(d["langs"]), "tier": 2 if d.get("revenue") else 3, "revenue_path": revenue,
                        "domain": d["key"], "anchor": False, "batch": stem in batch})
    return out


def _cap_for(spec: dict, rng: random.Random, server: str, server_label: str) -> tuple[float, str]:
    cc = spec["callee_caps"].get(server)
    if cc is not None:
        return float(cc["cap"]), cc["why"]
    if server_label == "Datastore":
        return 1.0, ""
    mix = spec["same_domain_mix"]
    r = rng.random()
    if r < mix["sync"]:
        return 1.0, ""
    if r < mix["sync"] + mix["best_effort"]:
        return 0.02, spec["best_effort_why"]
    return 0.0, spec["async_why"]


@lru_cache(maxsize=4)
def generate(seed: int = 42) -> Topology:
    spec = load_spec()
    rng = random.Random(seed * SEED_SALT + 1)
    services = _services(spec, rng)
    datastores = [dict(d) for d in spec["datastores"]]
    externals = [dict(e) for e in spec["externals"]]
    entry = spec["entry"]
    platform = {d["key"] for d in spec["domains"] if d.get("platform")}

    order = [s["id"] for s in services] + [d["id"] for d in datastores] + [e["id"] for e in externals]
    if len(set(order)) != len(order):
        raise ValueError("duplicate component ids in the globex spec")
    idx = {n: i for i, n in enumerate(order)}
    label = {s["id"]: "Service" for s in services}
    label.update({d["id"]: "Datastore" for d in datastores})
    label.update({e["id"]: "ExternalDependency" for e in externals})
    domain = {s["id"]: s["domain"] for s in services}
    domain.update({d["id"]: d["owner"] for d in datastores})
    tier = {s["id"]: s["tier"] for s in services}
    tier.update({d["id"]: 1 for d in datastores})
    tier.update({e["id"]: 1 for e in externals})
    svc = {s["id"]: s for s in services}

    # 1. backbone
    calls: dict[tuple[str, str], dict[str, Any]] = {}
    deliveries = set()
    for c in spec["calls"]:
        cl, sv = c["client"], c["server"]
        if cl not in idx or sv not in idx:
            raise ValueError(f"backbone call {cl}->{sv} names an unknown component")
        if label[cl] == "Datastore":
            deliveries.add((cl, sv))  # the bus delivers to its consumers (the only order exception)
        elif idx[cl] >= idx[sv]:
            raise ValueError(f"backbone call {cl}->{sv} goes against the domain order")
        if float(c["cap"]) < 1.0 and not c.get("why"):
            raise ValueError(f"backbone call {cl}->{sv}: a best-effort/async cap needs a reason")
        calls[(cl, sv)] = {"rps": int(c["rps"]), "cap": float(c["cap"]), "why": c.get("why", "")}

    # 2. preferential attachment (walk the order backwards so servers exist before their callers choose)
    backbone_only = set(spec["backbone_only"])
    indeg = {n: 0 for n in order}
    for (_, sv) in calls:
        indeg[sv] += 1
    for u in reversed([s["id"] for s in services]):
        if u == entry:
            continue
        s = svc[u]
        if s["domain"] == "edge":
            k = rng.choice((1, 2))
        else:
            k = rng.choice((2, 3, 3, 4)) if s["anchor"] else rng.choice((1, 1, 2, 2, 3))
        cands: list[tuple[str, float]] = []
        for v in order[idx[u] + 1:]:
            if (u, v) in calls or v in backbone_only or label[v] == "ExternalDependency":
                continue
            if label[v] == "Datastore" and domain[v] != s["domain"]:
                continue  # a datastore is only used by its own domain
            if label[v] == "Service" and svc[v]["batch"]:
                continue  # nobody calls a timer-driven job
            if domain[v] == s["domain"]:
                loc = 6.0
            elif label[v] == "Service" and svc[v]["anchor"]:
                loc = 2.0 if domain[v] in platform else 0.15  # other domains are reached through their anchors
            else:
                continue
            cands.append((v, (indeg[v] + 1) * loc))
        for _ in range(min(k, len(cands))):
            r, acc, j = rng.random() * sum(w for _, w in cands), 0.0, 0
            for j, (_, w) in enumerate(cands):
                acc += w
                if r <= acc:
                    break
            v = cands.pop(j)[0]
            cap, why = _cap_for(spec, rng, v, label[v])
            calls[(u, v)] = {"rps": None, "cap": cap, "why": why}
            indeg[v] += 1

    # 3. every non-batch service has a caller (an earlier anchor of its domain, else the fallback BFF)
    for s in services:
        v = s["id"]
        if v == entry or s["batch"] or indeg[v] > 0:
            continue
        earlier = [x["id"] for x in services if x["domain"] == s["domain"] and idx[x["id"]] < idx[v] and not x["batch"]]
        anchors = [x for x in earlier if svc[x]["anchor"]]
        u = (anchors or earlier or [spec["fallback_caller"]])[0]
        if idx[u] >= idx[v]:
            u = entry
        calls[(u, v)] = {"rps": None, "cap": 1.0, "why": ""}
        indeg[v] += 1

    # 4. no cycles, by construction: every other edge goes forward in `order`, and a delivery (bus → consumer)
    #    can only close a cycle if a consumer sits before a publisher of the same bus (checked here, no traversal)
    for bus in sorted({cl for (cl, _) in deliveries}, key=idx.get):
        publishers = [cl for (cl, sv) in calls if sv == bus]
        consumers = [sv for (cl, sv) in deliveries if cl == bus]
        if publishers and min(idx[c] for c in consumers) <= max(idx[p] for p in publishers):
            raise ValueError(f"{bus}: a consumer precedes a publisher in the domain order (possible cycle)")
        if any(sv == bus for (cl, sv) in calls if cl in consumers):
            raise ValueError(f"{bus}: a consumer publishes back to its own bus")

    # 5. traffic matrix in `order` (every caller of a node comes earlier, except deliveries, whose rps is fixed)
    inbound = {n: 0 for n in order}
    inbound[entry] = int(spec["entry_rps"])
    for (cl, sv), c in calls.items():
        if c["rps"] is not None:
            inbound[sv] += c["rps"]
    out_edges: dict[str, list[str]] = {n: [] for n in order}
    for (cl, sv) in sorted(calls, key=lambda e: (idx[e[0]], idx[e[1]])):
        out_edges[cl].append(sv)
    for n in order:
        if label[n] == "Service" and svc[n]["batch"] and inbound[n] == 0:
            inbound[n] = rng.randint(5, 30)  # timer-driven jobs generate their own load
        for m in out_edges[n]:
            c = calls[(n, m)]
            if c["rps"] is None:
                c["rps"] = max(1, round(max(inbound[n], 1) * rng.uniform(0.15, 0.8)))
                inbound[m] += c["rps"]

    call_list = [Call(cl, sv, int(c["rps"]), float(c["cap"]), c["why"])
                 for (cl, sv), c in sorted(calls.items(), key=lambda kv: (idx[kv[0][0]], idx[kv[0][1]]))]
    endpoints = [dict(e) for e in spec["endpoints"]]
    eps = {e["id"]: e for e in endpoints}
    for e in endpoints:
        if label.get(e["service"]) != "Service":
            raise ValueError(f"endpoint {e['id']} exposes unknown service {e['service']}")
    flow_pairs = {(c.server, c.client) for c in call_list if c.cap > 0}
    flags = [dict(f) for f in spec["flags"]]
    for f in flags:
        if f["gates"] not in label and f["gates"] not in eps:
            raise ValueError(f"flag {f['id']} gates unknown {f['gates']}")
        if f.get("cuts") and tuple(f["cuts"]) not in flow_pairs:
            raise ValueError(f"flag {f['id']} cuts {f['cuts']}, which is not a failure-flow edge")
    for s in services:
        s.pop("anchor", None)
    return Topology(entry, services, datastores, externals, call_list, endpoints, flags, label, domain, tier)


def build(seed: int = 42) -> Bundle:
    t = generate(seed)
    entry_rps = float(weights()["impact"]["entry_rps"])
    b = Bundle()
    for s in t.services:
        b.node("Service", s["id"], tenant=TENANT, name=s["name"], lang=s["lang"], tier=s["tier"],
               revenue_path=s["revenue_path"], status="active", entry=(s["id"] == t.entry), domain=s["domain"],
               batch=s["batch"])
    for d in t.datastores:
        b.node("Datastore", d["id"], tenant=TENANT, name=d["name"], kind=d["kind"], tier=1)
    for e in t.externals:
        b.node("ExternalDependency", e["id"], tenant=TENANT, name=e["name"], kind=e["kind"], tier=1)
    for c in t.calls:
        b.edge("CALLS", t.label[c.client], c.client, t.label[c.server], c.server, rps=c.rps, err_rate=0.0, p99_ms=0.0)
        if c.cap > 0:
            cut_cost = (c.rps / entry_rps) * tier_weight(t.tier[c.client])
            flow(b, t.label[c.server], c.server, t.label[c.client], c.client, c.cap, cut_cost, "service", rps=c.rps,
                 via_endpoint="", cap_why=c.why or "synchronous call; errors propagate")
    for e in t.endpoints:
        b.node("Endpoint", e["id"], tenant=TENANT, service_id=e["service"], route=e["route"], protocol=e["protocol"])
        b.edge("EXPOSES", "Service", e["service"], "Endpoint", e["id"])
    for f in t.flags:
        cuts = f.get("cuts") or [None, None]
        b.node("FeatureFlag", f["id"], tenant=TENANT, key=f["id"], state=f["state"], note=f.get("note", ""),
               cuts_src=cuts[0], cuts_dst=cuts[1])
        target = f["gates"]
        b.edge("GATES", "FeatureFlag", f["id"], "Endpoint" if ":" in target else t.label[target], target, cap=1.0, w=1)
    return b
