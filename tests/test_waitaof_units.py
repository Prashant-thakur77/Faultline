"""M20 #5 (unit): WAITAOF after the write-back. The write and WAITAOF share one connection; a timeout or an error is
UNKNOWN (VERIFY does not count the re-read: "0/7", escalated), never a green "7/7"."""

import contextlib

import redis

from faultline.actions import act
from faultline.graph import client as gclient


class _Conn:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def execute_command(self, *a):
        self.calls.append(a)
        if self.exc:
            raise self.exc
        return self.reply


def test_wait_aof_reads_the_engine_reply():
    ok = gclient.wait_aof(_Conn([1, 0]), timeout_ms=100)
    assert ok["ok"] and ok["local"] == 1 and ok["replicas"] == 0
    late = gclient.wait_aof(_Conn([0, 0]), timeout_ms=100)
    assert not late["ok"] and "timed out" in late["error"]
    err = gclient.wait_aof(_Conn(exc=redis.ResponseError("WAITAOF cannot be used when appendonly is disabled")),
                           timeout_ms=100)
    assert not err["ok"] and "appendonly" in err["error"]
    lost = gclient.wait_aof(_Conn(exc=redis.ConnectionError("gone")), timeout_ms=100)
    assert not lost["ok"]
    c = _Conn([1, 0])
    gclient.wait_aof(c, timeout_ms=1234)
    assert c.calls == [("WAITAOF", 1, 0, 1234)]


def _fake_write_back(monkeypatch, durable: dict):
    seen = {}
    conn = object()

    @contextlib.contextmanager
    def session(graph):
        seen["graph"] = graph
        yield "SESSION-GRAPH", conn

    def wb_applied(g, **kw):
        seen["write_graph"] = g
        return {"incident": kw["inc"], "postmortem": "pm-i", "decision": "DEC-i"}

    def waitaof(c, *, timeout_ms):
        seen["waitaof_conn"] = c
        return durable

    monkeypatch.setattr(act, "_action", lambda c, aid: {"verdict": "APPLIED", "kind": "flip_flag", "option": "o",
                                                        "external_ref": "pr#1"})
    monkeypatch.setattr(act.gclient, "engine_session", session)
    monkeypatch.setattr(act.gclient, "wait_aof", waitaof)
    monkeypatch.setattr(act.writes, "write_back_applied", wb_applied)
    monkeypatch.setattr(act, "verify_writeback", lambda c, **kw: {"verified": "7/7", "checks": {str(i): True for i in range(7)}})
    c = act.Ctx("acme", "eval_acme_x", "inc-1", "run-1")
    return act.write_back(c, "a1", cause="svc", confident=True, precedents=[]), seen, conn


def test_durable_write_back_counts(monkeypatch):
    out, seen, conn = _fake_write_back(monkeypatch, {"ok": True, "local": 1, "replicas": 0, "ms": 3.0})
    assert out["verified"] == "7/7" and out["durable"]["ok"]
    assert seen["write_graph"] == "SESSION-GRAPH" and seen["waitaof_conn"] is conn   # one connection for both
    assert seen["graph"] == "eval_acme_x"


def test_not_on_disk_is_unknown_never_counted(monkeypatch):
    out, _, _ = _fake_write_back(monkeypatch, {"ok": False, "local": 0, "replicas": 0, "ms": 2000.0,
                                               "error": "WAITAOF timed out after 2000 ms"})
    assert out["verified"] == "0/7" and "durability UNKNOWN" in out["reread_error"]
    n, m = (int(x) for x in out["verified"].split("/"))
    assert n != m        # the API and the reconciler escalate on n != m (UNKNOWN_ESCALATED), never RESOLVED


def test_new_engine_paths_fail_closed_when_the_graph_is_disabled(monkeypatch):
    """FAULTLINE_DISABLE_GRAPH (arm A4): the write-back session, guarded text2cypher (before any function catalogue
    read), the engine band and the freeze read all refuse instead of answering without FalkorDB."""
    import pytest

    from faultline.config import settings
    from faultline.graph import guard as G
    from faultline.graph.errors import GraphUnavailable
    from faultline.graph.ro import RO
    from faultline.preflight import score as P

    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    called = []
    monkeypatch.setattr(G, "allowed_functions", lambda fetch: called.append(1) or frozenset())
    with pytest.raises(GraphUnavailable):
        with gclient.engine_session("tenant_acme"):
            pass
    with pytest.raises(GraphUnavailable):
        RO("acme").run_guarded("MATCH (n:Service) RETURN n.id")
    with pytest.raises(GraphUnavailable):
        RO("acme").run("Q-MW-BAND", {"target": "x", "metric": "error_rate", "since": 0, "until": 1, "k": 3.0, "floor": 1.2})
    with pytest.raises(GraphUnavailable):
        P.freezes(RO("acme"), ["payment"], at=0)
    assert called == []
