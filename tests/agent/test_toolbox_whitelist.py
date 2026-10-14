"""ToolBox enforcement without FalkorDB: a call outside the stage whitelist (or outside a caller's
narrower list) returns an error event, never reaches MCP or a tool, is logged and is recorded as a refused call."""

import types

import anyio
import pytest

from faultline.agent import loop
from faultline.agent.state import Stage


class _NoMCP:
    async def call_tool(self, name, args):  # pragma: no cover - must never be reached for a refused call
        raise AssertionError(f"MCP reached for {name}")


@pytest.fixture
def box(monkeypatch):
    recorded = []
    monkeypatch.setattr(loop.writes, "record_refused_call", lambda g, **kw: recorded.append(kw))
    run = types.SimpleNamespace(run_id="run-unit", tenant="acme", g=lambda: None, workflow={})
    b = loop.ToolBox(run, _NoMCP(), {"blast_radius": {}, "causal_paths": {}, "diff_summary": {}})
    b.recorded = recorded
    return b


def test_tool_outside_the_stage_whitelist_returns_an_error_event_and_is_logged(box, caplog):
    box.stage = Stage.INVESTIGATE
    with caplog.at_level("WARNING", logger="faultline.agent"):
        out = anyio.run(lambda: box.call("blast_radius", {"id": "x"}))
    assert out == {"error": "tool 'blast_radius' not allowed in stage INVESTIGATE"}
    assert box.log[-1]["tool"] == "blast_radius" and box.log[-1]["error"] == out["error"]
    assert box.recorded and box.recorded[-1]["tool"] == "blast_radius" and box.recorded[-1]["stage"] == "INVESTIGATE"
    assert "refused blast_radius" in caplog.text


def test_post_verdict_reads_are_refused_to_the_model_but_allowed_to_code_in_gate(box):
    from faultline.agent import phases

    out = anyio.run(lambda: box.call("residue_check", {}, stage=Stage.GATE, only=phases.llm_toolset(Stage.GATE),
                                     caller="model"))
    assert "not allowed in stage GATE for the model" in out["error"]
    assert box.recorded[-1]["tool"] == "residue_check"


def test_a_specialist_list_narrows_but_never_widens(box):
    from faultline.agent import phases

    box.stage = Stage.INVESTIGATE
    out = anyio.run(lambda: box.call("causal_paths", {"from_id": "a", "to_id": "b"},
                                     only=phases.specialist_toolset("code"), caller="code specialist"))
    assert out["error"] == "tool 'causal_paths' not allowed in stage INVESTIGATE for the code specialist"
    # a caller list naming a tool the STAGE does not allow does not let it through
    box.stage = Stage.ROUTE
    out = anyio.run(lambda: box.call("diff_summary", {"deploy_id": "d"}, only=["diff_summary"], caller="code specialist"))
    assert "not allowed in stage ROUTE" in out["error"]
    assert len(box.recorded) == 2
