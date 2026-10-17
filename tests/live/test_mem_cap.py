"""Live (M20 #2): FalkorDB's per-query memory cap stops a runaway query cleanly and the engine stays up.

The cap (weights.yaml engine.query_mem_capacity_mb) is applied as scripts/configure_falkordb.py applies it. A guarded
text2cypher query that tries to collect 50M eight-integer lists is stopped by the ENGINE (GraphMemoryCapExceeded, never 0 rows);
afterwards the engine answers PING and a product template on the tenant graph still returns its rows."""

import importlib.util
import time
from pathlib import Path

import pytest

from faultline.graph import client
from faultline.graph.errors import GraphMemoryCapExceeded
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
# eight integers per row: the cap is reached in a few million rows, well inside the guarded query's timeout even on a
# slow CI runner (collecting single integers took about 2 s locally against a 3 s timeout, and timed out on CI)
HOG = "UNWIND range(1, 50000000) AS x RETURN collect([x, x, x, x, x, x, x, x])[0] AS v"


def _cap() -> int:
    spec = importlib.util.spec_from_file_location("configure_falkordb", ROOT / "scripts" / "configure_falkordb.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.query_mem_capacity()


def test_runaway_query_is_stopped_by_the_engine_and_the_engine_stays_up(db):
    c = client.engine().connection
    cap = _cap()
    c.execute_command("GRAPH.CONFIG", "SET", "QUERY_MEM_CAPACITY", cap)       # the product's runtime config
    assert c.execute_command("GRAPH.CONFIG", "GET", "QUERY_MEM_CAPACITY")[1] == cap
    before = int(c.info("memory")["used_memory"])
    t0 = time.perf_counter()
    with pytest.raises(GraphMemoryCapExceeded):
        RO("acme").run_guarded(HOG)
    stopped_ms = (time.perf_counter() - t0) * 1000
    assert c.ping()
    rows = RO("acme").run("Q-COUNT-1", {}).rows                                 # the engine still serves templates
    assert rows and stopped_ms < 10_000
    after = int(c.info("memory")["used_memory"])
    assert after - before < cap                                                 # nothing of the hog is left behind
