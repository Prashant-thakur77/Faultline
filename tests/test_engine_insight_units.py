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
