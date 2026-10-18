"""Live (M14 #3): FalkorDB's FLEX UDF library, vendored and pinned, used inside GRAPH.RO_QUERY on decision paths:
fuzzy entity resolution (flex.text.jaroWinkler) and hidden-coupling strength (flex.sim.jaccard)."""

import importlib.util
from pathlib import Path

import pytest
import redis

from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("configure_falkordb", ROOT / "scripts" / "configure_falkordb.py")
cfg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfg)


@pytest.fixture(scope="module")
def acme(db):
    cfg.load_udfs(db.connection)                      # idempotent (REPLACE); what make up / seed / API start do
    tok = context.bind("acme")
    yield
    context.unbind(tok)


def test_flex_is_pinned_and_a_changed_file_is_refused(acme, monkeypatch, tmp_path):
    bad = tmp_path / "flex.js"
    bad.write_text("falkor.register('text.levenshtein', (a, b) => 0);")
    monkeypatch.setattr(cfg, "UDF_LIBS", {"flex": (str(bad), cfg.UDF_LIBS["flex"][1])})
    with pytest.raises(cfg.EngineMismatch, match="sha256"):
        cfg.load_udfs(redis.Redis())


def test_misspelt_component_resolves_in_the_engine_and_decoys_do_not(acme):
    r = T.resolve_entity(text="pyment")
    assert r["rows"][0]["id"] == "payment" and r["rows"][0]["via"] == "fuzzy" and r["rows"][0]["sim"] >= 0.92
    assert "Q-FIND-FUZZY" in r["template"]
    assert T.resolve_entity(text="payment")["template"] == "Q-FIND-ID"            # exact first; fuzzy only as fallback
    assert T.resolve_entity(text="quantum")["rows"] == []                           # below the floor: nothing


def test_hidden_coupling_strength_is_a_jaccard_overlap(acme):
    rows = {(x["cause"], x["hit"]): x for x in T.hidden_coupling()["rows"]}
    assert rows[("queue", "accounting")]["strength"] == 1.0                         # every queue-caused incident hit it
    # 6 incidents caused at recommendation, all hitting product-catalog, which is hit in 13 (impacted or symptom)
    assert rows[("recommendation", "product-catalog")]["strength"] == round(6 / 13, 3)
    order = [x["strength"] for x in T.hidden_coupling()["rows"]]
    assert order == sorted(order, reverse=True)


def test_hidden_coupling_does_not_count_incidents_the_hit_component_caused(db):
    """`hit` = incidents where B was impacted or the symptom; an incident B itself CAUSED is not a co-failure."""
    from faultline.graph import copy as gcopy
    from faultline.graph.tenant import scratch_graph

    name = scratch_graph("acme", "coupling-role-test")
    gcopy.copy_graph(db, "tenant_acme", name)
    try:
        db.select_graph(name).query("MERGE (n:Node {id:'product-catalog'}) "
                                    "CREATE (i:Node:Incident {id:'inc-coupling-role-test'})-[:AFFECTED {role:'cause'}]->(n)")
        tok = context.bind("acme", graph=name)
        try:
            rows = {(x["cause"], x["hit"]): x for x in T.hidden_coupling(component_ids=["recommendation"])["rows"]}
        finally:
            context.unbind(tok)
        assert rows[("recommendation", "product-catalog")]["strength"] == round(6 / 13, 3)   # unchanged by the new cause
    finally:
        db.select_graph(name).delete()


def test_status_reports_flex_loaded_and_shows_missing_loudly(acme, monkeypatch):
    from fastapi.testclient import TestClient

    from faultline import api
    from faultline.graph import udf

    c = TestClient(api.app)
    s = c.get("/api/status?tenant=acme").json()
    assert s["status"] == "ok" and s["udf"] == {"flex": "loaded", "faultline": "loaded"}
    assert s["udf_detail"]["flex"]["loaded_sha"] and s["udf_detail"]["faultline"]["loaded_sha"]
    monkeypatch.setattr(udf, "udf_status", lambda r: {"flex": {"state": "missing", "pinned_sha": "x", "loaded_sha": None}})
    assert c.get("/api/status?tenant=acme").json()["udf"] == {"flex": "missing"}
