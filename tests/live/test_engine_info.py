"""Live (M14 #4): engine self-observability: GRAPH.MEMORY / GRAPH.INFO / GRAPH.SLOWLOG, slow queries mapped back to
template ids, scoped to one tenant's graphs."""

import pytest

from faultline.graph import engine_info as E
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


def test_tenant_report_is_scoped_and_maps_slow_queries_to_templates(db):
    r = E.tenant_report("acme")
    assert {g for g in r["graphs"] if not g.startswith("eval_acme_")} <= {"tenant_acme", "golden_acme", "audit_acme"}
    assert "tenant_acme" in r["graphs"]
    assert r["load"]["running"] >= 0 and r["load"]["waiting"] >= 0
    assert all(not g.startswith(("tenant_globex", "golden_globex")) for g in r["graphs"])
    assert E.tenant_report("acme", graphs=["tenant_globex"])["graphs"] == {}          # another tenant's graph: refused


def test_slowlog_entry_from_a_template_is_attributed(db):
    name = "scratch_acme_slowlog_probe"
    g = db.select_graph(name)
    try:
        g.query("UNWIND range(1, 30000) AS i CREATE (:X {i: i})")                    # slow enough to be logged
        rows = E.slowlog(name)
        assert rows and rows[0]["ms"] > 0 and rows[0]["template"] is None             # ad-hoc text: not a template
        assert E.memory(name)["total_graph_sz_mb"] is not None
    finally:
        g.delete()
    RO("acme").run("Q-COUNT-1", {})                                                     # templates map by exact text
    idx = E._template_index()
    from faultline.graph.templates import load

    assert idx[E._norm(load("Q-COUNT-1").text)] == "Q-COUNT-1"


def test_engine_panel_endpoint_and_load_shedding(db, monkeypatch):
    from fastapi.testclient import TestClient

    from faultline import api
    from faultline.graph import engine_info as E2

    with TestClient(api.app) as client:
        r = client.get("/api/engine")
        assert r.status_code == 200, r.text
        out = r.json()
        assert "tenant_acme" in out["graphs"] and out["limits"]["max_waiting"] > 0
        assert out["slow_templates_over_budget"] == []                 # no product template over its slow-log budget
        monkeypatch.setattr(E2, "info", lambda: {"running": 3, "waiting": 99})
        busy = client.post("/api/scenarios/S1/run", json={})
        assert busy.status_code == 429 and "waiting" in busy.text      # the engine's own queue sheds the run


def test_engine_connection_errors_are_503_not_500(db, monkeypatch):
    """A refused engine connection is GraphUnavailable: /api/engine and the run route answer 503 like every route."""
    import redis
    from fastapi.testclient import TestClient

    from faultline import api
    from faultline.graph import engine_info as E2

    class Down:
        def execute_command(self, *a):
            raise redis.exceptions.ConnectionError("Connection refused")

        def list_graphs(self):
            raise redis.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(E2, "engine", lambda: type("Db", (), {"connection": Down(), "list_graphs": Down().list_graphs})())
    with pytest.raises(E2.GraphUnavailable):
        E2.info()
    with TestClient(api.app) as client:
        assert client.get("/api/engine").status_code == 503
        r = client.post("/api/scenarios/S1/run", json={})
        # review round 4, m12: the client sees a generic message + request id, never the raw engine error
        assert r.status_code == 503 and "FalkorDB unavailable" in r.text and "request id" in r.text
        assert "Connection refused" not in r.text


def test_engine_panel_is_rate_limited(db, monkeypatch):
    from fastapi.testclient import TestClient

    from faultline import api

    monkeypatch.setattr(api, "_rate", __import__("collections").defaultdict(list))
    with TestClient(api.app) as client:
        codes = [client.get("/api/engine").status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_tenant_report_covers_existing_clean_rooms(db):
    from faultline.graph import copy as gcopy

    room = "eval_acme_engine_probe_room"
    gcopy.copy_graph(db, "tenant_acme", room)
    try:
        r = E.tenant_report("acme")
        assert room in r["graphs"] and not any(g.startswith("eval_globex_") for g in r["graphs"])
    finally:
        gcopy.delete_if_exists(db, room)
