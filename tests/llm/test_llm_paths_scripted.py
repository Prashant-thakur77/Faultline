"""Live, keyless: the LLM code paths (investigator + brain) driven by a SCRIPTED fake Anthropic client, so the
wiring (tool schemas, tool results, workflow tools, gate, citation guard) is exercised before any real key or
money is used. The fake decides nothing clever: it calls tools in a fixed order and proposes whatever the
packet's suspects say; the gate and the guard still decide."""

import json
import types

import anyio
import pytest

from faultline import scenario
from faultline.config import settings

pytestmark = pytest.mark.live


def _block(**kw):
    return types.SimpleNamespace(**kw)


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls, self.schemas, self.history = script, 0, None, []

    def create(self, **kw):
        self.schemas = kw.get("tools")
        self.history.append([t["name"] for t in kw.get("tools") or []])  # the tool list offered on each call
        blocks = self.script(self.calls, kw["messages"])
        self.calls += 1
        return types.SimpleNamespace(content=blocks, usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))


class FakeAnthropic:
    instance = None

    def __init__(self, script):
        self.messages = FakeMessages(script)

    @classmethod
    def factory(cls, script):
        def make(*a, **k):
            cls.instance = cls(script)
            return cls.instance
        return make


def _tool_results(messages):
    out = []
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            out += [json.loads(r["content"]) for r in m["content"] if r.get("type") == "tool_result"]
    return out


def test_llm_investigator_wiring_with_scripted_model(monkeypatch):
    import anthropic

    from faultline.agent.loop import LLMInvestigator

    def script(turn, messages):
        packet = json.loads(messages[0]["content"].split("\n", 1)[1])
        if turn == 0:
            return [_block(type="tool_use", id=f"t{i}", name="metric_window",
                           input={"target_id": t, "onset_ms": packet["onset_ms"]})
                    for i, t in enumerate(["checkout"] + [s["target"] for s in packet["suspects"]])]
        if turn == 1:
            ev = [r["evidence_id"] for r in _tool_results(messages) if r.get("evidence_id")]
            return [_block(type="tool_use", id="c1", name="confirm_root_cause",
                           input={"cause_id": packet["suspects"][0]["id"], "evidence_ids": ev})]
        return [_block(type="tool_use", id="f1", name="finish", input={"summary": "scripted"})]

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    p, res = anyio.run(lambda: scenario.run("S1", LLMInvestigator(max_turns=6), set_mode=False, keep=False))
    assert res.error is None, res.trace
    assert res.outcome == "CONFIRMED" and res.cause_id == "D-pay-417"  # the gate accepted the proposal
    first = set(FakeAnthropic.instance.messages.history[0])  # INVESTIGATE: evidence tools + the gate's entry
    assert {"confirm_root_cause", "causal_paths", "impact_bound", "metric_window", "run_cypher_readonly"} <= first
    # per-stage (§6.2): after a confident acceptance the incident is in GATE and only the gate's tools are offered
    assert set(FakeAnthropic.instance.messages.history[-1]) == {"confirm_root_cause", "declare_no_incident",
                                                               "reachable_from_changes", "finish"}
    assert all(t["input_schema"].get("type") == "object" for t in FakeAnthropic.instance.messages.schemas)


def test_llm_investigator_cannot_confirm_a_distractor(monkeypatch):
    """A model that insists on the same-minute email deploy is refused by the gate every time."""
    import anthropic

    from faultline.agent.loop import LLMInvestigator

    def script(turn, messages):
        if turn < 3:
            return [_block(type="tool_use", id=f"c{turn}", name="confirm_root_cause",
                           input={"cause_id": "D-email-88", "evidence_ids": []})]
        return [_block(type="tool_use", id="f1", name="finish", input={"summary": "insisted"})]

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    p, res = anyio.run(lambda: scenario.run("S1", LLMInvestigator(max_turns=6), set_mode=False, keep=False))
    assert res.error is None, res.trace
    assert res.cause_id != "D-email-88" and res.outcome != "CONFIRMED"


def test_llm_brain_guard_refuses_a_hallucinated_id(monkeypatch):
    import anthropic

    from faultline.brain.ask import ask

    def script(turn, messages):
        if turn == 0:
            return [_block(type="tool_use", id="r1", name="resolve_entity", input={"text": "productcatalog"})]
        if turn == 1:
            return [_block(type="tool_use", id="b1", name="blast_radius", input={"id": "product-catalog"})]
        return [_block(type="text", text="If [product-catalog] fails, [checkout] breaks; ask [p-999] about it.")]

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    a = ask("What breaks if productcatalog goes down?", "acme", llm="anthropic")
    assert not a.guard["ok"] and a.guard["unseen"] == ["p-999"] and "withheld" in a.answer


def test_llm_comparison_arms_wiring(monkeypatch):
    """A0 (LLM-only) and A1 (vector-RAG) build their context and parse a JSON answer; grading is shared."""
    import sys
    from pathlib import Path

    import anthropic

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
    import llm_arms

    seen = {}

    def script(turn, messages):
        seen["prompt"] = messages[0]["content"]
        return [_block(type="text", text='Looking at it: {"cause": "D-email-88", "why": "same minute"}')]

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    r0 = llm_arms.arm_a0("S1", "fake-model")
    assert r0["cause"] == "D-email-88" and "CHANGES IN THE WINDOW" in seen["prompt"] and "checkout:" in seen["prompt"]
    r1 = llm_arms.arm_a1("S1", "fake-model")
    assert r1["cause"] == "D-email-88" and "RETRIEVED CONTEXT" in seen["prompt"]
    assert llm_arms.estimate(1, 1, ["A0"])["trials"] == 1


@pytest.mark.slow
def test_llm_proposes_data_repair_which_becomes_the_gated_option(monkeypatch):
    """S2 live-mode path: the model proposes a transform patch during INVESTIGATE; after the gate it becomes the
    enabled data_repair option (diff computed server-side). Nothing is applied without approval."""
    from pathlib import Path

    import anthropic

    from faultline.agent.loop import LLMInvestigator

    path = Path(__file__).resolve().parents[2] / "pipeline" / "transforms" / "stg_orders.sql"
    original = path.read_text()
    fixed = original.replace("    CAST(amount AS DOUBLE) AS amount,",
                             "    CASE WHEN payment_processor = 'cloudpay_v2' THEN CAST(amount AS DOUBLE) / 100.0 "
                             "ELSE CAST(amount AS DOUBLE) END AS amount,")

    def script(turn, messages):
        packet = json.loads(messages[0]["content"].split("\n", 1)[1])
        if turn == 0:
            return [_block(type="tool_use", id="h", name="get_metric_history", input={}),
                    _block(type="tool_use", id="r", name="read_transform", input={"name": "stg_orders"}),
                    _block(type="tool_use", id="p", name="propose_repair",
                           input={"file": "pipeline/transforms/stg_orders.sql", "new_content": fixed,
                                  "reasoning": "cloudpay_v2 reports integer cents"})]
        if turn == 1:
            ev = [r["evidence_id"] for r in _tool_results(messages) if r.get("evidence_id")]
            return [_block(type="tool_use", id="c", name="confirm_root_cause",
                           input={"cause_id": packet["suspects"][0]["id"], "evidence_ids": ev})]
        return [_block(type="tool_use", id="f", name="finish", input={"summary": "scripted"})]

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    try:
        p, res = anyio.run(lambda: scenario.run("S2", LLMInvestigator(max_turns=6), set_mode=True, keep=False))
        assert res.error is None, res.trace
        if res.outcome == "CONFIRMED":
            opt = next(o for o in res.post_gate["options"] if o["kind"] == "data_repair")
            assert opt["enabled"] and opt["args"]["diff"].startswith("--- a/pipeline/transforms/stg_orders.sql")
        assert path.read_text() == original  # proposing never touches the file
    finally:
        path.write_text(original)
        scenario.set_pipeline_mode("incident")


def test_llm_tool_outside_the_stage_whitelist_is_refused_logged_and_recorded(monkeypatch):
    """§6.2: the model is offered INVESTIGATE's list; a call to a BLAST/RECALL tool (or a post-verdict advisory read)
    returns an error event, is logged in the ToolBox and is recorded in the run as a refused ToolCall."""
    import anthropic

    from faultline.agent import phases
    from faultline.agent.loop import LLMInvestigator
    from faultline.agent.state import Stage
    from faultline.graph import client as gclient
    from faultline.graph import copy as gcopy

    def script(turn, messages):
        packet = json.loads(messages[0]["content"].split("\n", 1)[1])
        if turn == 0:
            assert set(packet["specialists"]) == {"topology", "telemetry", "data", "change", "code"}
            return [_block(type="tool_use", id="x1", name="blast_radius", input={"id": "checkout"}),
                    _block(type="tool_use", id="x2", name="residue_check", input={"incident_id": "x", "cause_id": "y"})]
        if turn == 1:
            refused = [r for r in _tool_results(messages) if "not allowed in stage INVESTIGATE" in str(r.get("error"))]
            assert len(refused) == 2, _tool_results(messages)
            return [_block(type="tool_use", id="f1", name="finish", input={"summary": "refused calls only"})]
        raise AssertionError("no further turns expected")

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic.factory(script))
    monkeypatch.setattr(settings, "anthropic_api_key", "test-not-a-real-key")
    p, res = anyio.run(lambda: scenario.run("S1", LLMInvestigator(max_turns=3), set_mode=False, keep=True))
    try:
        assert res.error is None, res.trace
        offered = FakeAnthropic.instance.messages.history[0]
        assert offered == phases.llm_toolset(Stage.INVESTIGATE)
        assert "blast_radius" not in offered and "similar_incidents" not in offered and "residue_check" not in offered
        rows = gclient.engine().select_graph(p.graph).ro_query(
            "MATCH (:Run {id: $run})-[:HAS_TOOL_CALL]->(tc:ToolCall) WHERE tc.refused = true "
            "RETURN tc.tool, tc.stage, tc.error ORDER BY tc.tool", {"run": p.run_id}).result_set
        assert [r[0] for r in rows] == ["blast_radius", "residue_check"] and all(r[1] == "INVESTIGATE" for r in rows)
        assert all("not allowed in stage INVESTIGATE" in r[2] for r in rows)
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
