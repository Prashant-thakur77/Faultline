"""Public-mode brain scratch graphs (review round 4, M2).

On the public demo a visitor's question must not write into the live tenant graph without bound. Each question's Run,
tool calls, evidence (SAW edges) and session turns are recorded instead in a per-tenant scratch COPY of the tenant
graph, `scratch_<t>_brain_<epoch>_<rand>` (GRAPH.COPY; one of the tenant's own graphs, `graph_belongs_to`, inside the
`ro_<t>` ACL). The question's tools read the same copy, so the SAW edges point at real nodes and the citation guard
(Q-CITE-1) reads the very graph the run was recorded in.

Bounded: a copy is replaced by a fresh one once it is older than weights.yaml brain.scratch_ttl_min or holds
brain.scratch_max_runs runs recorded since it was made (Q-BRAIN-RUNS counts runs after the copy's Meta.scratch_born,
stamped on the engine clock; runs copied over from the tenant graph do not count), and every older copy no question is
using is deleted. A copy is also stale once its content epoch (Meta.epoch, inherited from the tenant graph) differs
from the tenant graph's: re-arm and an operator's forget stamp a new epoch, so a copy made before a re-arm is retired
even when the re-arm ran in another process (`make seed`). `invalidate` retires every copy at once in this process.
Making a copy sheds load first (engine_info.check_capacity), like every other graph copy. The only process state is the count of questions in flight per copy (handles, like
the API's job handles); the generations themselves are read from FalkorDB (GRAPH.LIST). One API process is assumed,
as for the job handles.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from ..agent.weights import weights
from ..graph import client
from ..graph import copy as gcopy
from ..graph import writes
from ..graph.ro import RO
from ..graph.tenant import check_tenant, tenant_graph

_LOCK = threading.Lock()
_INFLIGHT: dict[str, int] = {}   # copy → questions using it right now
_RETIRED: set[str] = set()       # copies invalidated while in use: never handed out again, deleted when idle


def prefix(tenant: str) -> str:
    return f"scratch_{check_tenant(tenant)}_brain_"


def generations(tenant: str) -> list[str]:
    """This tenant's brain copies, oldest first (the name carries its creation time)."""
    p = prefix(tenant)
    return sorted(g for g in client.engine().list_graphs() if g.startswith(p) and re.fullmatch(r"\d{10}_[0-9a-f]{6}", g[len(p):]))


def born_s(name: str) -> int:
    return int(name.rsplit("_", 2)[-2])


def _epoch(tenant: str, graph: str | None) -> str | None:
    rows = RO(tenant, graph).run("Q-META-1", {}).rows
    return rows[0].get("epoch") if rows else None


def _fresh(tenant: str, name: str, now_s: float) -> bool:
    w = weights()["brain"]
    if name in _RETIRED or now_s - born_s(name) > float(w["scratch_ttl_min"]) * 60:
        return False
    if _epoch(tenant, name) != _epoch(tenant, None):  # the tenant graph was re-armed or forgot something since
        return False
    return int(RO(tenant, name).run("Q-BRAIN-RUNS", {}).rows[0]["runs"]) < int(w["scratch_max_runs"])


def _collect(tenant: str, keep: str | None) -> list[str]:
    """Delete every copy but `keep` that no question is using (caller holds _LOCK)."""
    db = client.engine()
    gone = []
    for g in generations(tenant):
        if g != keep and not _INFLIGHT.get(g):
            gcopy.delete_if_exists(db, g)
            _RETIRED.discard(g)
            gone.append(g)
    return gone


@contextmanager
def use(tenant: str) -> Iterator[str]:
    """The brain copy a public question records in (created or replaced here when stale); held until it returns."""
    t = check_tenant(tenant)
    with _LOCK:
        gens = generations(t)
        cur = gens[-1] if gens else None
        if cur is None or not _fresh(t, cur, time.time()):
            from ..graph import engine_info

            engine_info.check_capacity()  # EngineOverloaded (429) before a new copy, like every other graph copy
            cur = f"{prefix(t)}{int(time.time()):010d}_{uuid.uuid4().hex[:6]}"
            db = client.engine()
            gcopy.copy_graph(db, tenant_graph(t), cur)
            writes.stamp_scratch_born(db.select_graph(cur))
        _INFLIGHT[cur] = _INFLIGHT.get(cur, 0) + 1
        _collect(t, cur)
    try:
        yield cur
    finally:
        with _LOCK:
            _INFLIGHT[cur] -= 1
            if not _INFLIGHT[cur]:
                _INFLIGHT.pop(cur)
                if cur in _RETIRED:
                    gcopy.delete_if_exists(client.engine(), cur)
                    _RETIRED.discard(cur)


def current(tenant: str) -> str | None:
    """The newest brain copy (where a visitor's session history lives now), or None."""
    gens = generations(tenant)
    return gens[-1] if gens and gens[-1] not in _RETIRED else None


def invalidate(tenant: str) -> list[str]:
    """Retire every brain copy of the tenant (the tenant graph changed under them): idle ones are deleted now, ones in
    use when their last question returns. The next question copies the tenant graph afresh."""
    t = check_tenant(tenant)
    with _LOCK:
        for g in generations(t):
            if _INFLIGHT.get(g):
                _RETIRED.add(g)
        return _collect(t, None)


def gc(tenant: str) -> list[str]:
    """Collect stale brain copies (API startup and the periodic collector): keep the newest one while it is fresh."""
    t = check_tenant(tenant)
    with _LOCK:
        gens = generations(t)
        keep = gens[-1] if gens and _fresh(t, gens[-1], time.time()) else None
        return _collect(t, keep)


__all__ = ["use", "current", "invalidate", "gc", "generations", "prefix"]
