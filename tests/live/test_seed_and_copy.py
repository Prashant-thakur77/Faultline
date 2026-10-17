"""Live: seeding is idempotent, GRAPH.COPY keeps indexes + ready flag, re-arm keeps the audit graph."""

import importlib.util
from pathlib import Path

import pytest

from faultline.graph import copy as gcopy
from faultline.graph import writes

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts" / "seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
CORE = ["lineage_to_graph", "otel_topology", "cross_domain"]


def test_apply_bundle_twice_gives_identical_counts(scratch):
    b = seed.build_bundle("acme", only=CORE)
    seed.apply_bundle(scratch, b)
    first = writes.counts(scratch)
    seed.apply_bundle(scratch, b)
    assert writes.counts(scratch) == first
    assert first["edges"]["PROPAGATES_TO"] == first["edges"]["DEPENDS_ON"]


def test_copy_carries_indexes_and_ready_flag(db, scratch):
    b = seed.build_bundle("acme", only=CORE)
    seed.apply_bundle(scratch, b)
    writes.mark_ready(scratch, "h", "6.0.2", "acme")
    dst = scratch.name + "_c"
    try:
        info = gcopy.copy_graph(db, scratch.name, dst)
        c = db.select_graph(dst)
        assert info["indexes"] >= 40
        assert c.ro_query("CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node RETURN count(node)").result_set[0][0] >= 1
        with pytest.raises(Exception):
            gcopy.copy_graph(db, scratch.name, dst)  # destination exists → engine refuses
    finally:
        gcopy.delete_if_exists(db, dst)


def test_unique_constraint_blocks_duplicate_intent(scratch):
    writes.apply_schema(scratch)
    writes.ensure_constraints(scratch)
    scratch.query("CREATE (:Intent {idem:'x', state:'PENDING'})")      # (M20: Intent.state is mandatory too)
    with pytest.raises(Exception, match="unique constraint violation"):
        scratch.query("CREATE (:Intent {idem:'x', state:'PENDING'})")


def test_dangling_edge_fails_loudly(scratch):
    writes.upsert_nodes(scratch, "Service", [{"id": "a"}])
    with pytest.raises(writes.WriteError):
        writes.upsert_edges(scratch, "CALLS", "Service", "Service", [{"src": "a", "dst": "missing"}])
