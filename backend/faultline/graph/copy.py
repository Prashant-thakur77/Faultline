"""GRAPH.COPY: golden snapshots → tenant graphs, re-arm, what-if branches, eval clean rooms.

The destination must not exist (engine-enforced; smoke 17). After every copy the schema is
re-applied and the copy is checked for the ready flag and its index count (fail loudly)."""

from __future__ import annotations

import re
import time
import uuid

from falkordb import FalkorDB

from . import writes
from .errors import GraphNotReady
from .tenant import audit_graph, check_tenant, golden_graph, tenant_graph


def exists(db: FalkorDB, name: str) -> bool:
    return name in set(db.list_graphs())


def delete_if_exists(db: FalkorDB, name: str) -> bool:
    if exists(db, name):
        db.select_graph(name).delete()
        return True
    return False


def copy_graph(db: FalkorDB, src: str, dst: str, deadline_s: float = 30.0) -> dict:
    if not exists(db, src):
        raise GraphNotReady(f"source graph {src} does not exist; run `make seed`")
    t0 = time.perf_counter()
    db.select_graph(src).copy(dst)
    g = db.select_graph(dst)
    end = time.time() + deadline_s
    while time.time() < end:  # copy is fast, but never trust it before the ready flag is readable
        rows = g.ro_query("MATCH (m:Meta) RETURN m.ready LIMIT 1").result_set
        if rows:
            break
        time.sleep(0.05)
    schema = writes.apply_schema(g)
    idx = g.ro_query("CALL db.indexes() YIELD label RETURN count(label)").result_set[0][0]
    ready = g.ro_query("MATCH (m:Meta) RETURN m.ready LIMIT 1").result_set
    if not ready or not ready[0][0]:
        raise GraphNotReady(f"copy {src} → {dst} has no ready flag")
    return {"src": src, "dst": dst, "ms": round((time.perf_counter() - t0) * 1000, 1), "indexes": idx,
            "schema_reapplied": schema}


def swap_in(db: FalkorDB, src: str, dst: str) -> None:
    """Replace graph `dst` with `src` in ONE engine command (RENAME overwrites the destination key atomically; FalkorDB
    keeps the graph, its indexes and its name in step, checked on the pinned engine, tests/live/test_rearm_swap.py)."""
    db.connection.execute_command("RENAME", src, dst)


def rearm(db: FalkorDB, tenant: str, reason: str = "manual", ip_hash: str = "") -> dict:
    """Restore tenant_<t> from golden_<t>; keep audit_<t> (it survives re-arm) and log the re-arm.
    The copy goes to a temporary scratch graph first and is then swapped in with one RENAME (review round 4, m6):
    there is never a moment without tenant_<t>, so a write that lands during re-arm (a MERGE on the tenant graph)
    hits the old graph and is replaced with it, instead of recreating a half-empty tenant graph that the copy then
    fails on (GRAPH.COPY refuses an existing destination).
    Round 5: the new tenant graph gets a fresh content epoch (Meta.epoch) before the swap, so every brain scratch copy
    made from the old one is stale, also in another process; the temporary graph's name carries its creation time
    (`scratch_<t>_rearm_<epoch s>_<hex>`) so `make gc` never deletes one that is still being swapped in. The swap is
    the re-arm: if the audit row cannot be written afterwards, the result says so (`audit: "write failed"`) instead
    of reporting the re-arm as failed."""
    check_tenant(tenant)
    epoch = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    tmp = f"scratch_{tenant}_rearm_{int(time.time()):010d}_{uuid.uuid4().hex[:8]}"
    try:
        info = copy_graph(db, golden_graph(tenant), tmp)
        writes.set_epoch(db.select_graph(tmp), epoch)
        swap_in(db, tmp, tenant_graph(tenant))
    except BaseException:
        delete_if_exists(db, tmp)
        raise
    info = {**info, "dst": tenant_graph(tenant), "via": tmp, "epoch": epoch}
    try:
        writes.append_audit(db.select_graph(audit_graph(tenant)), "Rearm", {"reason": reason, "ip_hash": ip_hash,
                                                                            "copy_ms": info["ms"], "epoch": epoch})
        info["audit"] = "written"
    except Exception as e:  # noqa: BLE001 - the tenant graph IS re-armed; only its log line is missing
        import logging

        logging.getLogger("faultline.rearm").error("re-arm of %s done, audit write failed: %s", tenant, e)
        info["audit"] = "write failed"
    return info


_TIMED = re.compile(r"^scratch_[a-z0-9]+_(brain|rearm)_(\d{10})_[0-9a-f]+$")


def gc_eval_graphs(db: FalkorDB, tenant: str, keep: set[str], dry_run: bool = False,
                   now_s: float | None = None) -> list[str]:
    """Drop this tenant's eval/whatif/scratch graphs except those in `keep` (graphs that recent runs in the
    audit index still point at). Never touches tenant_/golden_/audit_ graphs. Round 5: a brain scratch copy is left
    to its own collector (the API's) until it is older than twice weights.yaml brain.scratch_ttl_min, and a re-arm's
    temporary graph until it is 10 minutes old: either may be in use by another process right now."""
    from ..agent.weights import weights
    from .tenant import check_tenant

    t = check_tenant(tenant)
    now_s = time.time() if now_s is None else now_s
    brain_ttl_s = 2 * float(weights()["brain"]["scratch_ttl_min"]) * 60
    prefixes = (f"eval_{t}_", f"whatif_{t}_", f"scratch_{t}_")

    def in_flight(g: str) -> bool:
        m = _TIMED.match(g)
        if not m:
            return g.startswith(f"scratch_{t}_brain_")  # a brain copy whose name we cannot date: leave it to the API
        age = now_s - int(m.group(2))
        return age < (brain_ttl_s if m.group(1) == "brain" else 600)

    doomed = sorted(g for g in db.list_graphs() if g.startswith(prefixes) and g not in keep and not in_flight(g))
    if not dry_run:
        for g in doomed:
            delete_if_exists(db, g)
    return doomed
