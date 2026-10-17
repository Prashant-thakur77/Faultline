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


# ---------------------------------------------------------------------------------------------------------------------
# M20 #8: FalkorDB's own per-query telemetry (6.0.2 writes a `telemetry{<graph>}` stream: one entry per query with
# "Received at", "Query", "Query parameters", "Total/Wait/Execution/Report duration" (ms), "Utilized cache", "Write",
# "Timeout"; trimmed to MAX_INFO_QUERIES, deleted with the graph). Unlike GRAPH.SLOWLOG (10 entries, ≥ 10 ms) it sees
# every query, so the engine itself reports queueing (wait), execution and plan-cache use per template.
# Public-safe by construction: entries are mapped to template ids (Q-…) or writer ids (W-…) and only ids, numbers and
# flags leave this module. The query text and the parameters (another visitor's input) are never returned.
_DURATIONS = {"Total duration": "total_ms", "Wait duration": "wait_ms", "Execution duration": "exec_ms",
              "Report duration": "report_ms"}
MAX_INSIGHT_ROOMS = 10          # eval clean rooms included per call (their streams go when the room is deleted)
TELEMETRY_COUNT = 1000          # entries read per graph (MAX_INFO_QUERIES keeps 1000)
RECENT = 20


def _writer_index() -> dict[str, str]:
    from . import writes

    return {_norm(v): k.replace("_", "-") for k, v in vars(writes).items() if k.startswith("W_") and isinstance(v, str)}


def _s(x: Any) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile (the convention of scripts/profile_templates.py)."""
    if not xs:
        return None
    ys = sorted(xs)
    return round(ys[max(0, min(len(ys) - 1, int(-(-q * len(ys) // 1)) - 1))], 4)


def _entries(graph: str, count: int) -> list[dict[str, Any]]:
    raw = engine().connection.execute_command("XREVRANGE", f"telemetry{{{graph}}}", "+", "-", "COUNT", int(count)) or []
    tidx, widx = _template_index(), _writer_index()
    out = []
    for item in raw:
        fields = item[1] if isinstance(item, (list, tuple)) else {}
        if isinstance(fields, (list, tuple)):        # a RESP2 flat [k, v, k, v] reply
            fields = {fields[i]: fields[i + 1] for i in range(0, len(fields) - 1, 2)}
        f = {_s(k): _s(v) for k, v in fields.items()}
        q = _norm(f.get("Query", ""))
        qid = tidx.get(q) or widx.get(q)
        e: dict[str, Any] = {"at": int(float(f.get("Received at") or 0)), "id": qid,
                             "kind": "template" if q in tidx else "write" if q in widx else None,
                             "cache": f.get("Utilized cache") == "1", "write": f.get("Write") == "1",
                             "timeout": f.get("Timeout") == "1"}
        for src, dst in _DURATIONS.items():
            try:
                e[dst] = float(f.get(src) or 0.0)
            except ValueError:
                e[dst] = None
        out.append(e)
    return out


def _aggregate(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict]] = {}
    other = []
    for e in entries:
        (by.setdefault(e["id"], []) if e["id"] else other).append(e)

    def stats(es: list[dict]) -> dict[str, Any]:
        col = {k: [x[k] for x in es if x.get(k) is not None] for k in _DURATIONS.values()}
        return {"n": len(es), "total_ms_p50": _pct(col["total_ms"], 0.5), "total_ms_p95": _pct(col["total_ms"], 0.95),
                "wait_ms_p50": _pct(col["wait_ms"], 0.5), "wait_ms_p95": _pct(col["wait_ms"], 0.95),
                "exec_ms_p50": _pct(col["exec_ms"], 0.5), "exec_ms_p95": _pct(col["exec_ms"], 0.95),
                "report_ms_p50": _pct(col["report_ms"], 0.5),
                "cache_pct": round(100.0 * sum(1 for x in es if x["cache"]) / len(es), 1),
                "writes": sum(1 for x in es if x["write"]), "timeouts": sum(1 for x in es if x["timeout"])}

    rows = [{"id": k, "kind": v[0]["kind"], **stats(v)} for k, v in by.items()]
    rows.sort(key=lambda r: (-r["n"], r["id"]))
    ats = [e["at"] for e in entries if e["at"]]
    return {"entries": len(entries), "from": min(ats) if ats else None, "to": max(ats) if ats else None,
            "queries": rows,
            # ad-hoc queries (guarded text2cypher, the official MCP server, operators): counted, never shown
            "unmapped": {"n": len(other), **({k: v for k, v in stats(other).items() if k != "n"} if other else {})}}


@_engine_call
def telemetry(graph: str, count: int = TELEMETRY_COUNT) -> dict[str, Any]:
    """One graph's telemetry stream, mapped and aggregated: per template/writer id n, total/wait/execution ms p50 and
    p95, report ms p50, plan-cache hit %, writes and timeouts; plus the most recent mapped entries (ids and numbers)."""
    es = _entries(graph, count)
    agg = _aggregate(es)
    agg["recent"] = [{k: e[k] for k in ("at", "id", "kind", "total_ms", "wait_ms", "exec_ms", "report_ms", "cache",
                                         "write", "timeout")} for e in es if e["id"]][:RECENT]
    return agg


@_engine_call
def engine_config() -> dict[str, Any]:
    """The engine limits a panel can show (GRAPH.CONFIG GET; numbers only)."""
    c = engine().connection
    out = {}
    for k in ("QUERY_MEM_CAPACITY", "TIMEOUT_MAX", "TIMEOUT_DEFAULT", "MAX_QUEUED_QUERIES", "CACHE_SIZE",
              "MAX_INFO_QUERIES", "THREAD_COUNT"):
        try:
            out[k] = c.execute_command("GRAPH.CONFIG", "GET", k)[1]
        except redis.exceptions.ResponseError:
            out[k] = None
    return out


@_engine_call
def insight(tenant: str) -> dict[str, Any]:
    """FalkorDB observing itself for one tenant (GET /api/engine/insight; response shape in docs/plans/M20.md "API"):
    per graph of the tenant (tenant_, golden_, oncall_, audit_ and up to MAX_INSIGHT_ROOMS live eval clean rooms) its
    GRAPH.MEMORY USAGE and its telemetry stream aggregated per template id; a combined per-template table over those
    graphs; engine load (GRAPH.INFO) and limits (GRAPH.CONFIG). Never another tenant's graph, never query text or
    parameters."""
    t = check_tenant(tenant)
    existing = set(engine().list_graphs())
    rooms = sorted(g for g in existing if g.startswith(f"eval_{t}_"))
    names = [g for g in [f"tenant_{t}", f"golden_{t}", f"oncall_{t}", f"audit_{t}"] + rooms[:MAX_INSIGHT_ROOMS]
             if g in existing and graph_belongs_to(g, t)]
    out: dict[str, Any] = {"tenant": t, "load": info(), "config": engine_config(), "graphs": {},
                           "rooms_not_reported": max(0, len(rooms) - MAX_INSIGHT_ROOMS),
                           "source": "GRAPH.MEMORY USAGE + the engine's telemetry{graph} stream (FalkorDB 6.0)",
                           "privacy": "template and writer ids, timings and flags only; no query text, no parameters"}
    every: list[dict] = []
    for g in names:
        try:
            mem = memory(g)
            es = _entries(g, TELEMETRY_COUNT)
        except redis.exceptions.ResponseError:     # deleted since list_graphs (a clean room): nothing left to report
            continue
        every += es
        tel = _aggregate(es)
        tel["recent"] = [{k: e[k] for k in ("at", "id", "kind", "total_ms", "wait_ms", "exec_ms", "report_ms", "cache",
                                             "write", "timeout")} for e in es if e["id"]][:RECENT]
        out["graphs"][g] = {"memory_mb": mem.get("total_graph_sz_mb"),
                            "memory": {k: v for k, v in mem.items() if isinstance(v, (int, float, dict))},
                            "telemetry": tel}
    out["templates"] = _aggregate(every)
    return out


__all__ = ["memory", "info", "slowlog", "tenant_report", "telemetry", "insight", "engine_config"]


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
