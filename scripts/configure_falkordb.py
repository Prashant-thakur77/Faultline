"""Apply runtime FalkorDB config (idempotent; run by `make up`/seed/API start).
TIMEOUT_MAX caps every query (reads and writes); the RO wrapper uses tighter per-query timeouts."""

from __future__ import annotations

import json
import sys

import redis

from faultline.config import settings
# FalkorDB UDF libraries: the pinned list and loader live in the package (graph/udf.py) so API startup shares them
from faultline.graph.udf import UDF_LIBS, UdfMismatch
from faultline.graph.udf import load_udfs as _load_udfs

# RESULTSET_SIZE silently truncates engine-side, so it is a high backstop only: templates carry literal LIMITs,
# the RO wrapper detects truncation, and exports page with ORDER BY/SKIP.
CONFIG = {"TIMEOUT_MAX": 10000, "TIMEOUT_DEFAULT": 2000, "RESULTSET_SIZE": 100000, "MAX_QUEUED_QUERIES": 50}


def query_mem_capacity() -> int:
    """QUERY_MEM_CAPACITY in bytes from weights.yaml engine.query_mem_capacity_mb (M20 #2): FalkorDB stops any single
    query above it with "Query's mem consumption exceeded capacity" (the RO wrapper raises GraphMemoryCapExceeded).
    GRAPH.CONFIG SET is not persisted across restarts, so deploy/docker-compose*.yml also pass it in FALKORDB_ARGS
    (tests/graph/test_engine_config.py keeps the two equal)."""
    from faultline.agent.weights import weights

    mb = int(weights()["engine"]["query_mem_capacity_mb"])
    if mb <= 0:
        raise ValueError("engine.query_mem_capacity_mb must be > 0 (0 would mean no per-query memory cap)")
    return mb * 1024 * 1024


def config() -> dict[str, int]:
    return {**CONFIG, "QUERY_MEM_CAPACITY": query_mem_capacity()}


class EngineMismatch(RuntimeError):
    pass


def verify_engine(r: redis.Redis) -> int:
    """Fail loudly if the running engine is not the one whose procedure names are resolved."""
    from faultline.graph.algo.registry import RESOLVED_PATH
    from faultline.graph.smoke.runner import engine_module_version

    expected = json.loads(RESOLVED_PATH.read_text()).get("module_ver")
    running = engine_module_version(r)
    if expected and running != expected:
        raise EngineMismatch(f"running FalkorDB module {running} != pinned {expected}; check FALKORDB_IMAGE or re-run make smoke-both")
    return running


def load_udfs(r: redis.Redis) -> dict:
    """Load each pinned UDF library (REPLACE is idempotent); a changed file raises EngineMismatch."""
    try:
        return _load_udfs(r, UDF_LIBS)
    except UdfMismatch as e:
        raise EngineMismatch(str(e)) from e


def apply() -> dict:
    r = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port,
                    username=settings.falkordb_engine_user or None, password=settings.falkordb_engine_password or None)
    out = {"engine_module": verify_engine(r)}
    for k, v in config().items():
        r.execute_command("GRAPH.CONFIG", "SET", k, v)
        out[k] = r.execute_command("GRAPH.CONFIG", "GET", k)[1]
    out["udf"] = load_udfs(r)
    return out


if __name__ == "__main__":
    print(apply())
    sys.exit(0)
