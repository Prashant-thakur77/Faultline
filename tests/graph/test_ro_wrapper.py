"""RO wrapper contract without an engine (M0 review regressions included)."""

import socket
from types import SimpleNamespace

import pytest
import redis

from faultline.config import settings
from faultline.graph import client
from faultline.graph.errors import GraphNotReady, GraphQueryError, GraphTimeout, GraphUnavailable
from faultline.graph.ro import RO, classify


class FakeNode:
    def __init__(self, id_, labels=("Node", "Service")):
        self.labels, self.properties = list(labels), {"id": id_}


class FakeGraph:
    def __init__(self, rows=None, header=("id", "score"), exc=None):
        self.calls = []
        self.rows = rows if rows is not None else [["svc-a", 1.0], ["svc-b", 0.5]]
        self.header, self.exc = header, exc

    def ro_query(self, q, params=None, timeout=None):
        self.calls.append(("ro_query", q, params, timeout))
        if self.exc:
            raise self.exc
        return SimpleNamespace(header=[[1, h] for h in self.header], result_set=self.rows)

    def query(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("RO wrapper must never call query()")


@pytest.fixture
def use(monkeypatch):
    def _use(g):
        monkeypatch.setattr(client, "ro_graph", lambda tenant, name=None, **kw: g)
        return g
    return _use


def test_ro_query_with_timeout_limit_plus_one_and_contract(use):
    g = use(FakeGraph())
    r = RO("acme").run("Q-FIND-SERVICE", {"text": "pay*"})
    kind, q, _, timeout = g.calls[0]
    assert kind == "ro_query" and timeout == settings.falkordb_timeout_ms
    assert q.rstrip().endswith("LIMIT 11") and r.cypher.rstrip().endswith("LIMIT 10")  # sent n+1, shown n
    assert [x["id"] for x in r.rows] == ["svc-a", "svc-b"] and not r.truncated
    assert {"svc-a", "svc-b"} <= r.seen_ids and len(r.digest) == 64 and r.served_by.startswith("FalkorDB ")


def test_truncation_detected_from_limit_plus_one(use):
    use(FakeGraph(rows=[[f"s{i}", 1.0] for i in range(11)]))
    r = RO("acme").run("Q-FIND-SERVICE", {"text": "x*"})
    assert len(r.rows) == 10 and r.truncated


def test_seen_ids_only_from_entities_and_declared_columns(use):
    # Q-GATE-2 declares only `earlier_upstream_changes`; echoing params must not count as seen
    use(FakeGraph(rows=[[True, 1, 2, ["dep-1"]]], header=("in_window", "cause_at", "onset_at", "earlier_upstream_changes")))
    r = RO("acme").run("Q-GATE-2", {"cause": "ghost", "onset": 1, "window_ms": 1})
    assert r.seen_ids == {"dep-1"}
    use(FakeGraph(rows=[[FakeNode("svc-x"), 1.0], [{"id": "not-an-entity"}, 0.1]]))
    r = RO("acme").run("Q-FIND-SERVICE", {"text": "x*"})
    assert "svc-x" in r.seen_ids and "not-an-entity" not in r.seen_ids


@pytest.mark.parametrize(
    "exc,kind",
    [
        (Exception("Query timed out"), GraphTimeout),
        (redis.ConnectionError("Connection timed out"), GraphUnavailable),
        (Exception("The query TIMEOUT parameter value cannot exceed the TIMEOUT_MAX config"), GraphQueryError),
        (Exception("Invalid graph operation on empty key"), GraphNotReady),
        (Exception("Invalid input"), GraphQueryError),
    ],
)
def test_classification_type_first(exc, kind):
    assert isinstance(classify(exc, "T"), kind)


def test_timeout_clamped_to_max(use, monkeypatch):
    g = use(FakeGraph())
    RO("acme").run("Q-FIND-SERVICE", {"text": "x*"}, timeout_ms=10**9)
    assert g.calls[0][3] == settings.falkordb_timeout_max_ms


def test_other_tenants_graph_rejected():
    with pytest.raises(ValueError):
        RO("acme", graph_name="tenant_globex")
    with pytest.raises(ValueError):
        RO("acme", graph_name="scratch_globex_x")
    RO("acme", graph_name="scratch_acme_inc_1")  # own derived graph is fine


def test_ablation_flag_wins_even_after_warm_cache(monkeypatch):
    client.reset_connections()
    ro = RO("acme")                       # constructed before the flip
    monkeypatch.setattr(client, "_engine", lambda: (_ for _ in ()).throw(AssertionError("cached engine used")))
    monkeypatch.setattr(settings, "faultline_disable_graph", True)

    def boom(*a, **k):
        raise AssertionError("network touched while FAULTLINE_DISABLE_GRAPH=true")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    with pytest.raises(GraphUnavailable):
        ro.run("Q-META-1", {})
    with pytest.raises(GraphUnavailable):
        client.engine()
    with pytest.raises(GraphUnavailable):
        client.ro_graph("acme")
