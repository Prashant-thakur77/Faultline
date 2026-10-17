"""M20 #8 (unit): the engine's telemetry stream is mapped to template / writer ids and aggregated; query text and
parameters never leave engine_info (a fake stream, no engine)."""

import json

from faultline.graph import engine_info as E
from faultline.graph import writes
from faultline.graph.templates import load


def _entry(i, query, params="CYPHER x='secret-param'", total=1.0, wait=0.2, exe=0.5, rep=0.3, cache="0", write="0",
           timeout="0"):
    return (f"179225123799{i}-0", {"Received at": str(1792251237 + i), "Query": query, "Query parameters": params,
                                   "Total duration": str(total), "Wait duration": str(wait),
                                   "Execution duration": str(exe), "Report duration": str(rep),
                                   "Utilized cache": cache, "Write": write, "Timeout": timeout})


class _Conn:
    def __init__(self, reply):
        self.reply = reply

    def execute_command(self, *a):
        assert a[0] == "XREVRANGE" and a[1] == "telemetry{tenant_acme}"
        return self.reply


class _Eng:
    def __init__(self, reply):
        self.connection = _Conn(reply)


def test_stream_is_mapped_aggregated_and_scrubbed(monkeypatch):
    t = load("Q-COUNT-1")
    reply = [_entry(0, t.text, total=2.0, cache="1"), _entry(1, t.text, total=4.0), _entry(2, t.text, total=6.0),
             _entry(3, writes.W_STAGE, write="1"), _entry(4, "MATCH (n) WHERE n.secret = 'literal-secret' RETURN n"),
             _entry(5, t.text, timeout="1")]
    monkeypatch.setattr(E, "engine", lambda: _Eng(reply))
    out = E.telemetry("tenant_acme")
    by = {r["id"]: r for r in out["queries"]}
    q = by["Q-COUNT-1"]
    assert q["kind"] == "template" and q["n"] == 4 and q["total_ms_p50"] == 2.0 and q["total_ms_p95"] == 6.0
    assert q["cache_pct"] == 25.0 and q["timeouts"] == 1 and q["writes"] == 0
    assert by["W-STAGE"]["kind"] == "write" and by["W-STAGE"]["writes"] == 1
    assert out["unmapped"]["n"] == 1 and out["entries"] == 6
    assert out["recent"][0]["id"] == "Q-COUNT-1" and len(out["recent"]) == 5
    text = json.dumps(out)
    assert "secret" not in text and "MATCH" not in text and "CYPHER" not in text   # no query text, no parameters


def test_percentile_is_nearest_rank():
    assert E._pct([5.0, 1.0, 3.0], 0.5) == 3.0 and E._pct([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0 and E._pct([], 0.5) is None


# ---- the additive fields the /engine page reads: overall percentiles, a combined recent list, engine identity and
# constraint counts per graph (a fake engine with two graphs, no FalkorDB)
def _e(stream_id, query, total, received):
    return (stream_id, {"Received at": str(received), "Query": query, "Query parameters": "CYPHER x='secret-param'",
                        "Total duration": str(total), "Wait duration": "0.1", "Execution duration": "0.2",
                        "Report duration": "0.3", "Utilized cache": "0", "Write": "0", "Timeout": "0"})


class _Multi:
    """XREVRANGE per graph key (streams newest first, as the engine returns them)."""

    def __init__(self, streams):
        self.streams = streams
        self.connection = self

    def execute_command(self, *a):
        assert a[0] == "XREVRANGE"
        return self.streams[a[1][len("telemetry{"):-1]]

    def list_graphs(self):
        return list(self.streams)


def test_insight_adds_overall_percentiles_combined_recent_engine_and_constraints(monkeypatch):
    t = load("Q-COUNT-1").text
    streams = {
        "tenant_acme": [_e("1792251237500-1", t, 3.0, 1792251237), _e("1792251237500-0", t, 1.0, 1792251237),
                        _e("1792251200000-0", "MATCH (n) WHERE n.secret = 'literal-secret' RETURN n", 9.0, 1792251200)],
        "eval_acme_room": [_e("1792251237900-0", writes.W_STAGE, 2.0, 1792251237),
                           _e("1792251100000-0", t, 4.0, 1792251100)],
    }
    monkeypatch.setattr(E, "engine", lambda: _Multi(streams))
    monkeypatch.setattr(E, "memory", lambda g: {"total_graph_sz_mb": 1})
    monkeypatch.setattr(E, "info", lambda: {"running": 0, "waiting": 0})
    monkeypatch.setattr(E, "engine_config", lambda: {"QUERY_MEM_CAPACITY": 1})
    monkeypatch.setattr(E, "_constraints", lambda tenant, g: {"declared": 15, "operational": 15, "pending": 0,
                                                              "missing": 0, "expected": True})
    out = E.insight("acme")
    from faultline.graph.algo.registry import resolved_meta

    assert out["engine"] == {"version": resolved_meta()["engine"], "digest": resolved_meta()["digest"]}
    tm = out["templates"]
    # overall nearest-rank percentiles over every entry, mapped or not: [1, 2, 3, 4, 9]
    assert (tm["total_ms_p50"], tm["total_ms_p95"]) == (3.0, 9.0)
    g = out["graphs"]["tenant_acme"]
    assert (g["telemetry"]["total_ms_p50"], g["telemetry"]["total_ms_p95"]) == (3.0, 9.0)   # [1, 3, 9]
    assert g["constraints"]["operational"] == 15
    # merged by the stream id (ms, then sequence): the room's write at …900 ms, then the tenant's two at …500 ms
    assert [(r["id"], r["graph"], r["at_ms"]) for r in tm["recent"]] == [
        ("W-STAGE", "eval_acme_room", 1792251237900), ("Q-COUNT-1", "tenant_acme", 1792251237500),
        ("Q-COUNT-1", "tenant_acme", 1792251237500), ("Q-COUNT-1", "eval_acme_room", 1792251100000)]
    assert tm["recent"][1]["total_ms"] == 3.0                      # sequence 1 before sequence 0 within one ms
    assert "graph" not in g["telemetry"]["recent"][0]              # a graph's own list needs no graph name
    text = json.dumps(out)
    assert "secret" not in text and "MATCH" not in text and "CYPHER" not in text   # still ids and numbers only


def test_combined_recent_is_capped_at_twenty():
    es = [{"id": "Q-COUNT-1", "at": 1, "at_ms": 1000 + i, "_seq": 0, "_graph": "tenant_acme", "kind": "template",
           **{k: 0.1 for k in ("total_ms", "wait_ms", "exec_ms", "report_ms")}, "cache": False, "write": False,
           "timeout": False} for i in range(30)]
    r = E._recent(es)
    assert len(r) == E.RECENT == 20 and r[0]["at_ms"] == 1029 and r[-1]["at_ms"] == 1010
