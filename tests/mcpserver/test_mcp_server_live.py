"""Live: graph tools called through a real MCP client session (in-memory transport) give the
designed answers, fail loudly on bad input, and — when an agent run is bound — record
(:ToolCall)-[:SAW]->(n) + (:Evidence) in the graph."""

import anyio
import pytest
from mcp.client import Client

from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.mcp_server import context
from faultline.mcp_server.server import build_server

pytestmark = pytest.mark.live


def call(name, args, run_id=None):
    async def go():
        token = context.bind("acme", run_id=run_id) if run_id else None
        try:
            async with Client(build_server()) as c:
                r = await c.call_tool(name, args)
                return r.structured_content
        finally:
            if token:
                context.unbind(token)
    return anyio.run(go)


@pytest.fixture(scope="module", autouse=True)
def acme_ready(db):
    if not gcopy.exists(db, "golden_acme"):
        pytest.skip("acme not seeded")
    yield
    gcopy.rearm(gclient.engine(), "acme", reason="test cleanup")


def test_tools_are_listed_read_only():
    async def go():
        async with Client(build_server()) as c:
            return (await c.list_tools()).tools
    from faultline.agent.phases import INTERNAL_TOOLS
    from faultline.mcp_server.server import WRITE_TOOLS

    tools = anyio.run(go)
    assert len(tools) >= 17
    # honest annotations: tools that build a scratch graph, and `remember` (a note to agentmem_<t>), say they write;
    # every other tool is read-only
    assert all(t.annotations.read_only_hint is (t.name not in INTERNAL_TOOLS | WRITE_TOOLS) for t in tools)
    assert {t.name for t in tools} >= WRITE_TOOLS


def test_hero_answers_through_mcp():
    assert call("causal_paths", {"from_id": "payment", "to_id": "checkout"})["via"] == "payment → checkout"
    assert call("causal_paths", {"from_id": "recommendation", "to_id": "checkout"})["rows"] == []
    email = call("impact_bound", {"suspect_ids": ["email"], "symptom_id": "checkout", "observed_share": 0.407})
    assert email["verdict"] == "insufficient" and email["flow_share"] == pytest.approx(0.02)
    cut = call("containment_cut", {"failing_id": "payment", "protect_ids": ["frontend-proxy", "kpi.exec_revenue"]})
    assert {(c["u"], c["v"]) for c in cut["rows"]} == {("payment", "checkout"), ("payment", "raw.raw_orders")}


def test_bad_input_is_a_loud_error():
    assert "error" in call("causal_paths", {"from_id": "", "to_id": "checkout"})
    assert "error" in call("impact_bound", {"suspect_ids": ["email"], "symptom_id": "checkout", "observed_share": 7})


def test_bound_run_records_toolcall_saw_and_evidence(db):
    out = call("causal_paths", {"from_id": "payment", "to_id": "checkout"}, run_id="run-test-1")
    assert out["grounded_ids"] == 2
    g = db.select_graph("tenant_acme")
    saw = g.ro_query("MATCH (:Run {id:'run-test-1'})-[:HAS_TOOL_CALL]->(:ToolCall)-[:SAW]->(n) RETURN collect(n.id)").result_set[0][0]
    ev = g.ro_query("MATCH (e:Evidence {id:$e}) RETURN e.template, e.kind", {"e": out["evidence_id"]}).result_set
    assert set(saw) == {"payment", "checkout"} and ev == [["Q-GATE-1", "path"]]
