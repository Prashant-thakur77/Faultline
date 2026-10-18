"""Seed golden graphs and tenant graphs (idempotent): `make seed [TENANT=acme]`.

golden_<t> is built with UNWIND … MERGE (batches of 300) from deterministic ingest bundles, gets
the schema (indexes + the engine-enforced constraints of graph/constraints.py), normalised flow properties and finally
(:Meta {ready:true, data_hash}). If golden_<t> already holds the same data_hash it is reused (the schema, the
constraints and the vector-index options are re-applied to it). The tenant's policies (data/gen/policies) are merged in
last.
Then tenant_<t> = GRAPH.COPY golden_<t> (re-armed). Prints node/edge counts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import time

from faultline.graph import client, copy as gcopy, writes
from faultline.graph.algo import registry
from faultline.graph.tenant import golden_graph, tenant_graph
from faultline.ingest import policies
from faultline.ingest.bundle import Bundle

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import configure_falkordb as configure  # noqa: E402

PRODUCERS = {
    "acme": [
        "faultline.ingest.lineage_to_graph",
        "faultline.ingest.otel_topology",
        "faultline.ingest.cross_domain",
        "faultline.ingest.baselines",
        "faultline.ingest.org_gen",
        "faultline.ingest.obligations",
        "faultline.ingest.history",
        "faultline.ingest.docs",
        "faultline.ingest.embeddings",
        "faultline.ingest.brain_intents",  # the brain's question router (IntentExemplar nodes; tenant-agnostic)
    ],
    "globex": [  # generated scale tenant (data/topology/globex.yaml → ingest/globex/)
        "faultline.ingest.globex.topology",
        "faultline.ingest.globex.org",
        "faultline.ingest.globex.obligations",
        "faultline.ingest.globex.history",
        "faultline.ingest.globex.docs",
        "faultline.ingest.globex.embeddings",
        "faultline.ingest.brain_intents",
    ],
}
MEMORY_LABELS = {"Incident", "Postmortem", "Runbook", "Symptom", "Action"}


def build_bundle(tenant: str, no_memory: bool = False, only: list[str] | None = None) -> Bundle:
    if tenant not in PRODUCERS:
        raise SystemExit(f"no producers configured for tenant {tenant!r}")
    b = Bundle()
    for mod in PRODUCERS[tenant]:
        if only and mod.rsplit(".", 1)[-1] not in only:
            continue
        b.merge(importlib.import_module(mod).build())
    if not only:  # M14 #7: which service calls a historical PR introduced (valid_from on the edge pair)
        from faultline.ingest.topology_history import annotate

        annotate(b, tenant)
    if no_memory:
        for label in MEMORY_LABELS:
            b.nodes.pop(label, None)
        b.edges = {k: v for k, v in b.edges.items() if k[1] not in MEMORY_LABELS and k[2] not in MEMORY_LABELS}
    return b


# bump when a seed-time DERIVED property changes (writes.normalise_flow_props, …): the data hash alone would let an
# existing golden graph be reused without it (found when PROPAGATES_TO.share was added for G4 upstream)
DERIVED_VERSION = "derived-2: PROPAGATES_TO.share"


def data_hash(b: Bundle) -> str:
    canon = json.dumps({"nodes": {k: sorted(v, key=lambda r: r["id"]) for k, v in b.nodes.items()},
                        "edges": {"|".join(k): v for k, v in sorted(b.edges.items())}},
                       sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256((DERIVED_VERSION + "\n" + canon).encode()).hexdigest()


def apply_bundle(g, b: Bundle) -> dict:
    writes.apply_schema(g)
    writes.unmark_ready(g) if g.ro_query("MATCH (m:Meta) RETURN count(m)").result_set[0][0] else None
    t0 = time.perf_counter()
    for label in sorted(b.nodes):
        vecs = [r for r in b.nodes[label] if "embedding" in r]
        writes.upsert_nodes(g, label, b.nodes[label])
        if vecs:
            writes.set_vectors(g, label, vecs)
    for (rel, sl, dl) in sorted(b.edges):
        writes.upsert_edges(g, rel, sl, dl, b.edges[(rel, sl, dl)])
    writes.normalise_flow_props(g)
    writes.ensure_constraints(g)
    return {"apply_s": round(time.perf_counter() - t0, 2)}


def seed(tenant: str, no_memory: bool = False, force: bool = False, only: list[str] | None = None) -> dict:
    configure.apply()  # runtime config + engine/pin check (fails loudly on a mismatch)
    db = client.engine()
    b = build_bundle(tenant, no_memory, only)
    h = data_hash(b)
    golden = golden_graph(tenant, nomem=no_memory)
    g = db.select_graph(golden)
    reused = False
    if not force and gcopy.exists(db, golden):
        meta = g.ro_query("MATCH (m:Meta) RETURN m.ready, m.data_hash LIMIT 1").result_set
        reused = bool(meta and meta[0][0] and meta[0][1] == h)
    info: dict = {"golden": golden, "data_hash": h[:12], "reused": reused}
    if reused:  # an index added to schema.cypher since the golden graph was built (M19: Page, Contract, …) lands here
        info["schema"] = writes.apply_schema(g)   # idempotent: "already indexed" is tolerated
    if not reused:
        gcopy.delete_if_exists(db, golden)
        g = db.select_graph(golden)
        info.update(apply_bundle(g, b))
        if not no_memory:  # procedural memory from the seeded history (families → derived runbooks)
            from faultline.memory.learn import consolidate_all

            info["derived_runbooks"] = len(consolidate_all(tenant, golden))
        writes.mark_ready(g, h, registry.resolved_meta().get("engine") or "?", tenant)
    # company rules as data (M20 #6): applied AFTER every other node and edge, on a new or a reused golden graph alike,
    # so no existing node or edge id moves (some algorithms break ties by id); idempotent MERGE
    info["policies"] = policies.apply(g, tenant)
    # document text as searchable chunks (T3, Q-KNOW-1): also applied after everything else, idempotent
    from faultline.ingest import chunks

    info["chunks"] = chunks.apply(g)
    if not no_memory:
        info["copy"] = gcopy.rearm(db, tenant, reason="seed")
    info["counts"] = writes.counts(db.select_graph(tenant_graph(tenant) if not no_memory else golden))
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--no-memory", action="store_true", help="build golden_<t>_nomem (memory-off eval arms)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", help="limit to producer module names (dev)")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    tenants = list(PRODUCERS) if a.tenant == "all" else [a.tenant]
    for t in tenants:
        info = seed(t, a.no_memory, a.force, a.only)
        n, e = sum(info["counts"]["nodes"].values()), sum(info["counts"]["edges"].values())
        if a.summary:
            print(f"{t}: {n} nodes, {e} edges")
        else:
            print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
