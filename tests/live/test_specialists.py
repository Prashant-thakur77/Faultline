"""Live: specialists on the product path (§6.13) and structural G7 (§6.4).

* the five specialists run in parallel from INVESTIGATE, each on a W-CLAIM-1 work item, and their contracts land on
  the run's Task nodes (NAMES / CITES) where the gate reads them;
* two dispatches of the same work item never both run it;
* G7 correlation agrees on the hero, and a code channel that points at another change downgrades confidence
  without rejecting the claim; G8 is attached and never blocks.
Grading reads the truth files here (tests only)."""

import json
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.agent import specialists
from faultline.agent.loop import BaselineInvestigator, run_incident
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.errors import GraphUnavailable
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
TRUTH = Path(__file__).resolve().parents[2] / "data" / "scenarios"
ROLES = {"topology", "telemetry", "data", "change", "code"}


def _truth(sid):
    return json.loads((TRUTH / f"{sid}.truth.json").read_text())


@pytest.fixture
def graphs():
    made = []
    yield made
    for g in made:
        gcopy.delete_if_exists(gclient.engine(), g)


def _run(p, investigator):
    return anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms,
                                          symptoms=p.symptoms, investigator=investigator, graph=p.graph, run_id=p.run_id,
                                          window_min=p.scenario.get("window_min")))


def _tasks(p):
    return RO(p.tenant, p.graph).run("Q-GATE-CORR", {"run": p.run_id, "cause": "", "chain": [],
                                                    "roles": sorted(ROLES)}).rows


def test_hero_specialists_record_contracts_g7_correlates_and_g8_is_attached_not_blocking(graphs):
    truth = _truth("S1")
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(p.graph)
    assert res.error is None, res.trace
    assert res.outcome == "CONFIRMED" and res.cause_id == truth["cause"] and res.confident
    assert set(res.specialists) == ROLES and not any(d["skipped"] or d["rejected"] for d in res.specialists.values())
    assert truth["cause"] in res.specialists["code"]["suspect_ids"] and res.specialists["code"]["limits"]
    assert res.specialists["data"]["status"] == "insufficient"  # a service incident: nothing for the data channel
    # every contract is on a done Task of this run, claimed by exactly one agent
    rows = _tasks(p)
    assert {r["role"] for r in rows} == ROLES and all(r["status"] in ("complete", "insufficient") for r in rows)
    claims = RO(p.tenant, p.graph).run("Q-TASK-1", {"ids": [r["task"] for r in rows]}).rows
    assert all(c["state"] == "done" and len(c["claimed_by"]) == 1 for c in claims)
    checks = {c["name"]: c for c in res.gate["checks"]}
    assert checks["G7 agreement"]["passed"] is True and checks["G7 correlation"]["passed"] is True
    assert checks["G7 correlation"]["template"] == "Q-GATE-CORR" and checks["G7 correlation"]["downgrade_only"]
    # G8: the violated decisions are attached (VIOLATES + check detail) and neither block nor downgrade
    assert checks["G8 contradiction"]["passed"] is False and checks["G8 contradiction"]["downgrade_only"]
    assert {v["decision"] for v in res.gate["violations"]} == set(truth["violates"])
    assert res.gate["passed"] and res.gate["confident"] and res.post_gate and res.post_gate["options"]


class _DoubleDispatch:
    """Dispatches the same work items twice, concurrently (a retry racing the original, or two workers)."""

    name = "test: double dispatch"

    def __init__(self):
        self.results = []

    async def investigate(self, box, run, packet):
        async def go(i):
            self.results.append(await specialists.dispatch(box, run, packet, dispatch_id=f"d{i}"))

        async with anyio.create_task_group() as tg:
            tg.start_soon(go, 1)
            tg.start_soon(go, 2)
        await box.call("finish", {"summary": "double dispatch"})
        return {}


def test_two_dispatches_of_the_same_work_item_never_both_run_it(graphs):
    p = scenario.prepare("S3", set_mode=False)
    graphs.append(p.graph)
    inv = _DoubleDispatch()
    res = _run(p, inv)
    assert res.error is None, res.trace
    a, b = inv.results
    for role in ROLES:
        ran = [d for d in (a[role], b[role]) if not d.skipped]
        skipped = [d for d in (a[role], b[role]) if d.skipped]
        assert len(ran) == 1 and len(skipped) == 1, role
        assert ran[0].task == skipped[0].task and skipped[0].owner == ran[0].agent and skipped[0].report is None
    rows = _tasks(p)
    assert len(rows) == len(ROLES)
    claims = RO(p.tenant, p.graph).run("Q-TASK-1", {"ids": [r["task"] for r in rows]}).rows
    assert all(c["state"] == "done" and len(c["claimed_by"]) == 1 for c in claims)
    # each specialist's tools ran once: one change_details per suspect, not two
    calls = gclient.engine().select_graph(p.graph).ro_query(
        "MATCH (:Run {id: $run})-[:HAS_TOOL_CALL]->(tc:ToolCall {tool: 'change_details'}) RETURN count(tc)",
        {"run": p.run_id}).result_set[0][0]
    change = next(d for d in (a["change"], b["change"]) if not d.skipped).report
    assert calls == len(change.suspect_ids) >= 1


def test_g7_ignores_a_code_channel_that_names_only_an_eliminated_change(graphs):
    """S1b plus one extra upstream deploy whose diff facts are about the component it changed. The code specialist can
    inspect only that deploy and names it, but the gate's sweep eliminates it. A channel that names only an
    eliminated change says nothing against the cause: G7 correlation is not evaluable, and the cause stays confident
    (review M13/M14: before, this downgraded a correct cause and no containment plan was offered)."""
    truth = _truth("S1b")
    p = scenario.prepare("S1b", set_mode=False)
    graphs.append(p.graph)
    g = gclient.engine().select_graph(p.graph)
    writes.inject_change(g, id="D-test-cart-1", target="cart", at=p.onset_ms - 2 * 60_000, kind="deploy",
                         title="cart: test-only deploy with diff facts", tenant=p.tenant)
    writes.assert_change_fact(g, change="D-test-cart-1", key="test.cart.batch_size", value=50, about="cart",
                              file="src/cart/main.cs")
    res = _run(p, BaselineInvestigator())
    assert res.error is None, res.trace
    sweep = {v["change"]: v for v in res.sweep}
    assert sweep["D-test-cart-1"]["status"] == "eliminated", sweep  # the gate itself is not fooled by the extra deploy
    assert res.specialists["code"]["status"] == "complete" and res.specialists["code"]["suspect_ids"] == ["D-test-cart-1"]
    checks = {c["name"]: c for c in res.gate["checks"]}
    assert checks["G7 correlation"]["passed"] is None and "not evaluable" in checks["G7 correlation"]["detail"]
    assert res.outcome == "CONFIRMED" and res.cause_id == truth["cause"] and res.confident
    assert res.post_gate and res.post_gate["options"]                 # containment is offered again


class _Crashing(specialists.REGISTRY["code"]):
    async def run(self, ctx):
        raise RuntimeError("diff service exploded")


class _CrashDispatch:
    """Dispatches the specialists with one role (code) that raises a non-contract exception."""

    name = "test: crashing specialist"

    def __init__(self):
        self.reports = None

    async def investigate(self, box, run, packet):
        self.reports = await specialists.dispatch(box, run, packet,
                                                  registry={**specialists.REGISTRY, "code": _Crashing})
        await box.call("finish", {"summary": "crash dispatch"})
        return {}


def test_a_crashing_specialist_is_insufficient_and_does_not_abort_the_run(graphs):
    p = scenario.prepare("S1", set_mode=False)
    graphs.append(p.graph)
    inv = _CrashDispatch()
    res = _run(p, inv)
    assert res.error is None, res.trace
    assert set(inv.reports) == ROLES                                         # the other four still reported
    code = inv.reports["code"]
    assert code.report.status == "insufficient" and "diff service exploded" in code.report.unknowns[0]
    assert code.rejected and "crashed" in code.rejected[0]
    assert all(inv.reports[r].report.status in ("complete", "insufficient") for r in ROLES - {"code"})
    rows = {r["role"]: r for r in _tasks(p)}
    assert rows["code"]["status"] == "insufficient"                         # its claimed Task is completed, not stuck
    claims = RO(p.tenant, p.graph).run("Q-TASK-1", {"ids": [r["task"] for r in rows.values()]}).rows
    assert all(c["state"] == "done" for c in claims)


class _Outage(specialists.REGISTRY["code"]):
    async def run(self, ctx):
        raise GraphUnavailable("FalkorDB unreachable (simulated)")


class _OutageDispatch(_CrashDispatch):
    name = "test: graph outage in a specialist"

    async def investigate(self, box, run, packet):
        self.reports = await specialists.dispatch(box, run, packet,
                                                  registry={**specialists.REGISTRY, "code": _Outage})
        await box.call("finish", {"summary": "outage dispatch"})
        return {}


def test_a_graph_outage_in_a_specialist_fails_the_run_loudly(graphs):
    """Unlike a crash, an outage is not 'insufficient': it propagates and the run ends FAILED with the reason."""
    p = scenario.prepare("S1", set_mode=False)
    graphs.append(p.graph)
    inv = _OutageDispatch()
    res = _run(p, inv)
    # the client-visible reason is generic (review round 5, minor 7); the engine's own text stays in the trace/log
    assert res.outcome == "FAILED" and "FalkorDB unavailable" in (res.error or "") and "request id" in res.error, \
        (res.outcome, res.error)
    assert "FalkorDB unreachable (simulated)" in (res.trace or "")
    assert inv.reports is None                                              # dispatch never returned a report set


def test_data_specialist_reads_its_scope_through_a_recorded_tool(graphs):
    try:
        p, res = anyio.run(lambda: scenario.run("S2", BaselineInvestigator(), set_mode=True, keep=True))
    finally:
        scenario.set_pipeline_mode("incident")                              # the fixture judge-check expects
    graphs.append(p.graph)
    assert res.error is None, res.trace
    calls = gclient.engine().select_graph(p.graph).ro_query(
        "MATCH (:Run {id: $run})-[:HAS_TOOL_CALL]->(tc:ToolCall {tool: 'baseline_columns'}) RETURN count(tc)",
        {"run": p.run_id}).result_set[0][0]
    assert calls >= 1
    assert "baseline_columns" in {e["tool"] for e in res.specialists["data"]["evidence"]}
