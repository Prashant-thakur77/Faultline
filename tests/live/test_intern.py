"""Live (M20 #11): MetricWindow's low-cardinality strings are written through intern() by writes.upsert_nodes: the
values and equality matches are unchanged, the engine's ObjectPool holds them, and GRAPH.MEMORY reports less attribute
memory than the same rows written plainly (30k nodes; measured at 100k: total 67 → 48 MB)."""

import uuid

import pytest

from faultline.graph import engine_info, writes

pytestmark = pytest.mark.live
N = 30_000


def _rows():
    return [{"id": f"mw-{i}", "target_id": f"svc-{i % 20:02d}", "metric": "error_rate", "kind": "live",
             "source": "simulator (servicegraph)", "minute": i % 60, "at": 1792000000000 + i * 60_000,
             "value": (i % 97) / 1000.0} for i in range(N)]


def test_interned_writes_keep_values_and_use_less_memory(db, monkeypatch):
    rows = _rows()
    sizes = {}
    for mode in ("plain", "interned"):
        name = f"scratch_acme_intern_{mode}_{uuid.uuid4().hex[:6]}"
        g = db.select_graph(name)
        try:
            g.query("CREATE INDEX FOR (n:Node) ON (n.id)")
            with monkeypatch.context() as m:
                if mode == "plain":
                    m.setattr(writes, "INTERNED", {})
                assert writes.upsert_nodes(g, "MetricWindow", rows) == N
            assert g.ro_query("MATCH (w:MetricWindow {target_id:'svc-03', kind:'live', metric:'error_rate'}) "
                              "RETURN count(w)").result_set[0][0] == N // 20
            assert g.ro_query("MATCH (w:MetricWindow {id:'mw-7'}) RETURN w.target_id, w.source, w.minute").result_set \
                == [["svc-07", "simulator (servicegraph)", 7]]
            if mode == "interned":
                pool = dict(db.connection.execute_command("GRAPH.INFO", "ObjectPool")[1])
                assert int(pool["Unique Objects in Pool"]) >= 23            # 20 targets + metric + kind + source
            writes.upsert_nodes(g, "MetricWindow", [{"id": "mw-7", "value": 0.5}])   # a row without the interned keys
            assert g.ro_query("MATCH (w:MetricWindow {id:'mw-7'}) RETURN w.target_id, w.value").result_set == [["svc-07", 0.5]]
            sizes[mode] = sum((engine_info.memory(name).get("amortized_node_attributes_by_label_sz_mb") or {}).values())
        finally:
            g.delete()
    assert sizes["interned"] < sizes["plain"], sizes
