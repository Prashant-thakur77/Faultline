"""Live: the context pack (M16.1) on the hero scenario: within budget, every item carries its provenance, the cause,
its causal path and the decisions it violates are in a 500-token pack, and the API route is read-only."""

import uuid

import pytest

from faultline import scenario
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def s1(db):
    p = scenario.prepare("S1", tag=uuid.uuid4().hex[:8], set_mode=False)
    yield p
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def _pack(p, budget):
    tok = context.bind(p.tenant, run_id=None, graph=p.graph)
    try:
        return T.context_pack(text=p.scenario["report"], targets=list(p.symptoms), at=p.onset_ms, budget_tokens=budget)
    finally:
        context.unbind(tok)


def test_a_500_token_pack_holds_the_cause_its_path_and_the_violated_decisions(s1):
    r = _pack(s1, 500)
    assert "error" not in r and r["tokens"] <= 500
    assert all(it["template"] and it["ids"] for it in r["rows"])
    ids = {i for it in r["rows"] for i in it["ids"]}
    assert {"D-pay-417", "payment", "checkout", "ADR-012", "ADR-013"} <= ids
    assert any(it["kind"] == "path" and it["ids"] and "D-pay-417" in it["ids"] for it in r["rows"])


def test_a_tiny_budget_keeps_the_nearest_items_first(s1):
    r = _pack(s1, 60)
    assert r["tokens"] <= 60 and r["rows"] and r["rows"][0]["kind"] == "alert"


def test_the_api_route_is_read_only(db):
    from fastapi.testclient import TestClient

    from faultline import api

    client = TestClient(api.app)
    before = gclient.engine().select_graph("tenant_acme").ro_query("MATCH (t:ToolCall) RETURN count(t)").result_set[0][0]
    res = client.post("/api/context_pack?tenant=acme", json={"text": "checkout errors are elevated", "targets": ["checkout"],
                                                             "budget_tokens": 300})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tokens"] <= 300 and body["rows"]
    after = gclient.engine().select_graph("tenant_acme").ro_query("MATCH (t:ToolCall) RETURN count(t)").result_set[0][0]
    assert after == before


def test_a_pack_built_from_a_truncated_source_says_so(db):
    """More than 20 changes upstream of the alert: Q-SUS-1 is cut at its LIMIT (20) and the pack names it (fail loudly)."""
    import copy
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
    import gate_bench

    c = next(x for x in gate_bench.generate(seed=20261015) if x["expected"]["outcome"] == "CONFIRMED")
    spec = copy.deepcopy(c["spec"])
    spec["inject"] += [{"change": f"D-many{i:03d}", "target": c["symptom"], "kind": "deploy", "at": "-5m",
                        "title": "x: change"} for i in range(110)]
    p = scenario.prepare(spec["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        r = _pack(p, 500)
        assert "Q-SUS-1" in r["truncated_sources"] and "TRUNCATED" in r["via"]
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_unknown_targets_and_unsearchable_text_are_refused_or_said(s1):
    tok = context.bind(s1.tenant, run_id=None, graph=s1.graph)
    try:
        bad = T.context_pack(text="checkout errors", targets=["no-such-svc"], at=s1.onset_ms)
        assert "unknown target" in bad["error"]   # never echoed back as if the graph had returned it
        odd = T.context_pack(text="?? !!", targets=["checkout"], at=s1.onset_ms, budget_tokens=200)
        assert "error" not in odd and "full-text entry skipped" in odd["via"] and odd["rows"]
        assert "error" in T.context_pack(text="x" * 3000, targets=["checkout"], at=s1.onset_ms)
    finally:
        context.unbind(tok)


def test_the_default_ranking_puts_the_change_on_the_broken_component_first(s1):
    tok = context.bind(s1.tenant, run_id=None, graph=s1.graph)
    try:
        an = T.context_pack(text=s1.scenario["report"], targets=list(s1.symptoms), at=s1.onset_ms, budget_tokens=500)
        di = T.context_pack(text=s1.scenario["report"], targets=list(s1.symptoms), at=s1.onset_ms, budget_tokens=500,
                            rank="distance")
    finally:
        context.unbind(tok)
    first = [it for it in an["rows"] if it["kind"] == "change"][0]
    assert "D-pay-417" in first["ids"] and "error-rate excess" in first["text"]   # payment broke; email did not
    assert [it["ids"] for it in di["rows"] if it["kind"] == "change"] != [it["ids"] for it in an["rows"] if it["kind"] == "change"]
