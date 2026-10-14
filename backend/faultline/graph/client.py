"""Connection factory. Two roles, never mixed:

* `engine()`: the engine user (seed, write-back, scratch/what-if graphs). Never given to the model.
* `ro_graph(tenant)`: a read-only connection whose ACL user may only run GRAPH.RO_QUERY /
  GRAPH.EXPLAIN on its own tenant keys. It uses `falkordb.Graph(redis.Redis(...))` because the
  `FalkorDB()` constructor issues INFO, which the minimal RO ACL user may not run (smoke item 22).
"""

from __future__ import annotations

from functools import lru_cache

import redis
from falkordb import FalkorDB, Graph

from ..config import settings
from .errors import GraphUnavailable
from .tenant import check_tenant, graph_belongs_to, tenant_graph

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


def reset_connections() -> None:
    """For tests and settings changes: drop cached connections and close RO pools."""
    _engine.cache_clear()
    while _RO_POOLS:
        _, conn = _RO_POOLS.popitem()
        try:
            conn.close()
        except Exception:
            pass
