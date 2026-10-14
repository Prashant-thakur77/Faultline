"""Engine self-observability: what FalkorDB itself reports about the graphs Faultline runs on (M14 #4).

GRAPH.MEMORY USAGE (memory per graph), GRAPH.INFO (running and waiting queries) and GRAPH.SLOWLOG (slow queries,
mapped back to our template ids). These are engine-operator reads on the engine connection, not tenant data reads:
they never return graph content, so they sit outside the tenant RO wrapper, like the readiness checks in copy.py.
"""

from __future__ import annotations

import functools
import re
from typing import Any, Callable

import redis

from .client import engine
from .errors import GraphUnavailable
from .templates import catalogue
from .tenant import check_tenant, graph_belongs_to


MAX_EVAL_GRAPHS = 100  # clean rooms reported per call (eval runs can leave many until gc_graphs collects them)


def _engine_call(fn: Callable) -> Callable:
    """A refused or dropped engine connection is GraphUnavailable (the API answers 503), never a bare redis error (500)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, OSError) as e:
            raise GraphUnavailable(f"FalkorDB unreachable ({type(e).__name__}: {e})") from e
    return wrapper


def _norm(q: str) -> str:
    """Whitespace-insensitive text with the executable LIMIT n+1 folded back to the template's LIMIT n."""
    return re.sub(r"\s+", " ", q).strip()


def _template_index() -> dict[str, str]:
    out = {}
    for tid, t in catalogue().items():
        out[_norm(t.text)] = tid
        out[_norm(t.display)] = tid
    return out


@_engine_call
def memory(graph: str) -> dict[str, Any]:
    """GRAPH.MEMORY USAGE as a dict (MB figures as the engine reports them; per-label breakdowns kept as dicts)."""
    raw = engine().connection.execute_command("GRAPH.MEMORY", "USAGE", graph)
    out: dict[str, Any] = {}
    it = iter(raw)
    for key in it:
        val = next(it, None)
        if isinstance(val, list):  # [label, mb, label, mb, ...]
            val = {str(val[i]): val[i + 1] for i in range(0, len(val) - 1, 2)}
        out[str(key)] = val
    return out


@_engine_call
def info() -> dict[str, Any]:
    """GRAPH.INFO: how many queries are running and waiting right now (engine-wide)."""
    raw = engine().connection.execute_command("GRAPH.INFO")
    sections: dict[str, Any] = {}
    for i in range(0, len(raw) - 1, 2):
        sections[str(raw[i]).lstrip("# ").strip().lower()] = raw[i + 1]
    running, waiting = sections.get("running queries") or [], sections.get("waiting queries") or []
    return {"running": len(running), "waiting": len(waiting)}


@_engine_call
def memory_pressure() -> dict[str, Any]:
    """INFO memory: used_memory against maxmemory (fraction None when maxmemory is 0, i.e. unlimited: nothing to
    compare against; the deploy sets it, docs/LIVE.md). Server stats only, never graph content."""
    try:
        raw = engine().connection.info("memory")
    except redis.exceptions.RedisError as e:  # refused (ACL) or failed: the engine's state is unknown, so unavailable
        raise GraphUnavailable(f"INFO memory failed ({type(e).__name__}: {e})") from e
    used, cap = int(raw.get("used_memory") or 0), int(raw.get("maxmemory") or 0)
    return {"used_memory": used, "maxmemory": cap, "fraction": (used / cap) if cap else None}


@_engine_call
def slowlog(graph: str) -> list[dict[str, Any]]:
    """GRAPH.SLOWLOG entries for one graph, each mapped to the template it came from (None = not a template)."""
    idx = _template_index()
    rows = []
    for entry in engine().connection.execute_command("GRAPH.SLOWLOG", graph) or []:
        at, cmd, query, ms = entry[0], entry[1], entry[2], entry[3]
        rows.append({"at": int(at), "command": str(cmd), "ms": float(ms), "template": idx.get(_norm(str(query))),
                     "query": str(query)[:300]})
    return sorted(rows, key=lambda r: -r["ms"])


@_engine_call
def tenant_report(tenant: str, graphs: list[str] | None = None) -> dict[str, Any]:
    """Memory and slow templates for a tenant's own graphs (never another tenant's), plus engine-wide load."""
    t = check_tenant(tenant)
    existing = set(engine().list_graphs())
    # the tenant's long-lived graphs, plus every eval_<t>_* clean room that exists right now (the gate's hot path runs
    # there; a clean room deleted before this call takes its slow-log entries with it)
    rooms = sorted(g for g in existing if g.startswith(f"eval_{t}_"))
    default = [f"tenant_{t}", f"golden_{t}", f"audit_{t}"] + rooms[:MAX_EVAL_GRAPHS]
    names = [g for g in (graphs or default) if graph_belongs_to(g, t)]
    out: dict[str, Any] = {"tenant": t, "load": info(), "graphs": {},
                           "clean_rooms_not_reported": 0 if graphs else max(0, len(rooms) - MAX_EVAL_GRAPHS)}
    for g in names:
        if g in existing:
            try:
                mem = memory(g)
                out["graphs"][g] = {"total_mb": mem.get("total_graph_sz_mb"), "slow": slowlog(g)[:10]}
            except redis.exceptions.ResponseError:  # a clean room deleted since list_graphs: nothing left to report
                continue
    return out


__all__ = ["memory", "info", "slowlog", "tenant_report"]


class EngineOverloaded(RuntimeError):
    """FalkorDB is too busy or too full for a new graph copy (the API answers 429 with this message)."""


def check_capacity() -> None:
    """Load shedding before anything copies a graph (a run, a clean room, a brain scratch copy, a re-arm): queries
    waiting (GRAPH.INFO) and memory (INFO memory over maxmemory, weights.yaml engine.max_memory_fraction) →
    EngineOverloaded. An engine that cannot be asked raises GraphUnavailable (503), never "fine"."""
    from ..agent.weights import weights

    w = weights()["engine"]
    waiting = info()["waiting"]
    mem = memory_pressure()
    if waiting > int(w["max_waiting"]):
        raise EngineOverloaded(f"FalkorDB has {waiting} queries waiting (GRAPH.INFO); try again in a few seconds")
    if mem["fraction"] is not None and mem["fraction"] > float(w["max_memory_fraction"]):
        raise EngineOverloaded(f"FalkorDB memory is at {mem['fraction']:.0%} of maxmemory (limit "
                               f"{float(w['max_memory_fraction']):.0%}); new graph copies are paused until old graphs "
                               "are collected")
