"""Live (M20 #8): FalkorDB's own telemetry stream through GET /api/engine/insight: a template run on the tenant graph
shows up under its id with the engine's wait / execution timings; the response never carries query text or parameters
(a marker sent as a parameter does not appear); another tenant's graphs are never reported; FAULTLINE_DISABLE_GRAPH
answers 503 (fail closed)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.config import settings
from faultline.graph import engine_info as E
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


def test_template_runs_are_reported_by_the_engine_and_nothing_private_leaks(db):
    marker = f"insight-marker-{uuid.uuid4().hex[:8]}"
    ro = RO("acme")
    for _ in range(3):
        ro.run("Q-COUNT-1", {})
    ro.run("Q-FIND-SERVICE", {"text": marker})           # the marker travels as a query PARAMETER
    with pytest.raises(Exception):
        ro.run_guarded(f"MATCH (n:Service) WHERE n.id = '{marker}' RETURN n.id AS id, flex.text.repeat('x', 2) AS r")
    with TestClient(api.app) as client:
        r = client.get("/api/engine/insight", params={"tenant": "acme"})
        assert r.status_code == 200, r.text
        out = r.json()
    g = out["graphs"]["tenant_acme"]
    q = next(x for x in g["telemetry"]["queries"] if x["id"] == "Q-COUNT-1")
    assert q["kind"] == "template" and q["n"] >= 3 and q["exec_ms_p50"] is not None and q["writes"] == 0
    assert g["memory_mb"] is not None and out["config"]["QUERY_MEM_CAPACITY"] > 0
    assert not any(k.startswith(("tenant_globex", "golden_globex", "oncall_globex")) for k in out["graphs"])
    assert any(x["id"] == "Q-FIND-SERVICE" for x in g["telemetry"]["queries"])
    assert marker not in json.dumps(out)                   # neither the parameter nor the ad-hoc query text


def test_insight_is_scoped_rate_limited_and_fails_closed(db, monkeypatch):
    with TestClient(api.app) as client:
        assert client.get("/api/engine/insight", params={"tenant": "Not A Tenant"}).status_code == 422
        monkeypatch.setattr(settings, "faultline_disable_graph", True)
        assert client.get("/api/engine/insight", params={"tenant": "acme"}).status_code == 503
        monkeypatch.setattr(settings, "faultline_disable_graph", False)
        api._rate.clear()
        codes = [client.get("/api/engine/insight", params={"tenant": "globex"}).status_code for _ in range(22)]
        assert codes[0] == 200 and 429 in codes
        api._rate.clear()
    rep = E.insight("globex")
    assert all(k.endswith("_globex") or k.startswith("eval_globex_") for k in rep["graphs"])
