"""Connection factory. Three roles, never mixed:

* `engine()`: the engine user (seed, write-back, scratch/what-if graphs). Never given to the model.
* `ro_graph(tenant)`: a read-only connection whose ACL user may only run GRAPH.RO_QUERY /
  GRAPH.EXPLAIN on its own tenant keys. It uses `falkordb.Graph(redis.Redis(...))` because the
  `FalkorDB()` constructor issues INFO, which the minimal RO ACL user may not run (smoke item 22).
* `mem_graph(tenant)`: the shared-notes writer. Its ACL user mem_<tenant> may run GRAPH.QUERY on exactly one key,
  agentmem_<tenant>, so FalkorDB itself refuses a note write aimed at the graph the gate reads.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import redis
from falkordb import FalkorDB, Graph

from ..config import settings
from .errors import GraphUnavailable
from .tenant import check_tenant, graph_belongs_to, memory_graph, tenant_graph

_SOCKET_TIMEOUT_S = 10.0


def _disabled_guard() -> None:
    if settings.faultline_disable_graph:
        raise GraphUnavailable("graph disabled (FAULTLINE_DISABLE_GRAPH=true)")


def engine() -> FalkorDB:
    """Engine connection. The ablation guard runs on EVERY call (never cached)."""
    _disabled_guard()
    return _engine()


@lru_cache(maxsize=1)
def _engine() -> FalkorDB:
    try:
        return FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            username=settings.falkordb_engine_user or None,
            password=settings.falkordb_engine_password or None,
            socket_timeout=_SOCKET_TIMEOUT_S,
            socket_connect_timeout=3.0,
        )
    except Exception as e:  # connection refused / auth failure → fail loudly
        raise GraphUnavailable(f"FalkorDB unreachable at {settings.falkordb_host}:{settings.falkordb_port}: {e}") from e


@contextmanager
def engine_session(graph_name: str) -> Iterator[tuple[Graph, redis.Redis]]:
    """One dedicated engine connection (not the pool): a write and the WAITAOF after it must share a connection,
    because WAITAOF waits for the earlier writes OF THAT CLIENT (M20 #5). Closed on exit."""
    _disabled_guard()
    try:
        conn = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port,
                           username=settings.falkordb_engine_user or None, password=settings.falkordb_engine_password or None,
                           socket_timeout=_SOCKET_TIMEOUT_S, socket_connect_timeout=3.0, single_connection_client=True)
    except Exception as e:  # noqa: BLE001
        raise GraphUnavailable(f"FalkorDB unreachable at {settings.falkordb_host}:{settings.falkordb_port}: {e}") from e
    try:
        yield Graph(conn, graph_name), conn
    finally:
        conn.close()


def wait_aof(conn: redis.Redis, *, timeout_ms: int, numlocal: int = 1, numreplicas: int = 0) -> dict[str, Any]:
    """WAITAOF numlocal numreplicas timeout on `conn`: blocks until this connection's earlier writes are fsynced to the
    local AOF (appendfsync everysec: within about a second). Never raises: a timeout (fewer copies than asked) or an
    error (AOF disabled, connection lost) comes back as ok=False with the reason, and the caller treats it as UNKNOWN."""
    t0 = time.perf_counter()
    try:
        local, replicas = conn.execute_command("WAITAOF", int(numlocal), int(numreplicas), int(timeout_ms))
    except (redis.RedisError, OSError) as e:
        return {"ok": False, "local": None, "replicas": None, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": f"{type(e).__name__}: {e}"[:300]}
    ok = int(local) >= numlocal and int(replicas) >= numreplicas
    out: dict[str, Any] = {"ok": ok, "local": int(local), "replicas": int(replicas),
                           "ms": round((time.perf_counter() - t0) * 1000, 1)}
    if not ok:
        out["error"] = f"WAITAOF timed out after {timeout_ms} ms ({local} local AOF copies, {replicas} replicas)"
    return out


def ro_acl_enabled() -> bool:
    return bool(settings.falkordb_ro_password)


_RO_POOLS: dict[str, redis.Redis] = {}


def _ro_redis(tenant: str, fresh: bool = False) -> redis.Redis:
    if fresh or tenant not in _RO_POOLS:
        kwargs: dict = dict(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            socket_timeout=_SOCKET_TIMEOUT_S,
            socket_connect_timeout=3.0,
        )
        if ro_acl_enabled():
            kwargs.update(username=f"ro_{tenant}", password=settings.falkordb_ro_password)
        if fresh:  # a separate connection (second-channel re-reads); the caller closes it
            return redis.Redis(single_connection_client=True, **kwargs)
        _RO_POOLS[tenant] = redis.Redis(**kwargs)
    return _RO_POOLS[tenant]


def ro_graph(tenant: str, graph_name: str | None = None, fresh: bool = False) -> Graph:
    """Read-only handle on the tenant graph (or one of the tenant's scratch/what-if graphs). fresh=True opens a
    separate single connection (close it via graph.client.close())."""
    _disabled_guard()
    check_tenant(tenant)
    name = graph_name or tenant_graph(tenant)
    if not graph_belongs_to(name, tenant):
        raise ValueError(f"graph {name!r} does not belong to tenant {tenant!r}")
    return Graph(_ro_redis(tenant, fresh), name)


def mem_acl_enabled() -> bool:
    return bool(settings.falkordb_mem_password)


_MEM_POOLS: dict[str, redis.Redis] = {}


def mem_graph(tenant: str) -> Graph:
    """Write handle on agentmem_<tenant> as the mem_<tenant> ACL user (GRAPH.QUERY on that key only). Without
    FALKORDB_MEM_PASSWORD (local dev without ACL) it is the engine user, and /api/status says so."""
    _disabled_guard()
    t = check_tenant(tenant)
    if t not in _MEM_POOLS:
        kwargs: dict = dict(host=settings.falkordb_host, port=settings.falkordb_port, socket_timeout=_SOCKET_TIMEOUT_S,
                            socket_connect_timeout=3.0)
        if mem_acl_enabled():
            kwargs.update(username=f"mem_{t}", password=settings.falkordb_mem_password)
        else:
            kwargs.update(username=settings.falkordb_engine_user or None, password=settings.falkordb_engine_password or None)
        _MEM_POOLS[t] = redis.Redis(**kwargs)
    return Graph(_MEM_POOLS[t], memory_graph(t))


def reset_connections() -> None:
    """For tests and settings changes: drop cached connections and close RO pools."""
    _engine.cache_clear()
    while _MEM_POOLS:
        _, conn = _MEM_POOLS.popitem()
        try:
            conn.close()
        except Exception:
            pass
    while _RO_POOLS:
        _, conn = _RO_POOLS.popitem()
        try:
            conn.close()
        except Exception:
            pass
