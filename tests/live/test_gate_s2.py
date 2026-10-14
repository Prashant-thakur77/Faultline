"""Live: Gate v2 on the S2 shape (data incident, cross-domain) in a GRAPH.COPY clean room.
Scenario literals live here (tests), never in the product package."""

import uuid

import pytest

from faultline.agent import datatools as D
from faultline.agent.gate import Gate
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
ONSET = 1_791_900_000_000
CUTOVER, KPI, FX = "D-cutover-test", "kpi.exec_revenue", "raw.raw_fx_rates"


@pytest.fixture
def room(db):
    if not gcopy.exists(db, "golden_acme"):
        pytest.skip("acme not seeded")
    name = f"eval_acme_gatetest_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(client.engine(), "golden_acme", name)
    g = db.select_graph(name)
    writes.inject_change(g, id=CUTOVER, target="payment", at=ONSET - 10 * 60_000, kind="data_cutover", tenant="acme")
    writes.raise_alert(g, id="al-test-kpi", target=KPI, metric="kpi_jump", at=ONSET)
    run, inc = f"run-{uuid.uuid4().hex[:6]}", f"inc-{uuid.uuid4().hex[:6]}"
    writes.open_incident(g, inc=inc, run=run, tenant="acme", title="KPI jump", report="KPI looks wrong",
                         onset=ONSET, symptoms=[{"id": f"sym-{inc}", "kind": "kpi_jump", "target": KPI}],
                         models="test", mode="test")
    yield g, name, run, inc
    gcopy.delete_if_exists(db, name)


def investigate(name, run):
    """What an investigator would do: look at changes, measure, profile. Returns evidence ids."""
    token = context.bind("acme", run_id=run, graph=name)
    try:
        ch = T.window_changes(onset=ONSET, window_min=30)
        assert CUTOVER in {r["deploy"] for r in ch["rows"]}
        evs = [D.get_metric_history()["evidence_id"], D.compare_to_baseline(last_days=5)["evidence_id"]]
        rs = D.anomalous_row_share(table="staging.stg_orders", column="amount", day="2026-08-09")
        assert rs["share"] == pytest.approx(1.0)
        evs.append(rs["evidence_id"])
        T.find_entities(text="fx rates", labels=["Table"])  # the FX table is now "seen"
        return evs
    finally:
        context.unbind(token)


def test_sweep_eliminates_fx_distractor_by_flow_and_keeps_cutover(room):
    g, name, run, inc = room
    investigate(name, run)
    writes.upsert_hypothesis(g, inc=inc, hid=f"hyp-{inc}-fx", cause=FX, status="open", reason="stale FX feed", origin="model")
    verdicts = {v.change: v for v in Gate("acme", run, inc, name).sweep()}
    assert verdicts[CUTOVER].status == "candidate"
    assert verdicts[FX].status == "eliminated" and "G5" in verdicts[FX].reason
    assert verdicts[FX].flow == pytest.approx(0.0692)


def test_confirm_cutover_passes_all_hard_checks(room):
    g, name, run, inc = room
    evs = investigate(name, run)
    writes.upsert_hypothesis(g, inc=inc, hid=f"hyp-{inc}-fx", cause=FX, status="open", reason="stale FX feed", origin="model")
    gate = Gate("acme", run, inc, name)
    gate.sweep()
    res = gate.confirm(CUTOVER, evs)
    detail = {c.name: (c.passed, c.detail) for c in res.checks}
    assert res.passed, detail
    assert res.chain[0] == CUTOVER and res.chain[-1] == KPI and "raw.raw_orders" in res.chain
    assert detail["G7 agreement"][0] is True and res.confident, detail


def test_confirm_rejects_distractor_and_ungrounded_cause(room):
    g, name, run, inc = room
    evs = investigate(name, run)
    gate = Gate("acme", run, inc, name)
    bad = gate.confirm(FX, evs)
    names = {c.name for c in bad.failed()}
    assert not bad.passed and {"G3 time", "G5 sufficiency"} <= names
    ghost = gate.confirm("D-never-seen", evs)
    assert not ghost.passed and "G1 grounded" in {c.name for c in ghost.failed()}
    assert "G2 path" in {c.name for c in ghost.failed()}


def test_gate_runs_are_recorded_including_rejections(room):
    g, name, run, inc = room
    evs = investigate(name, run)
    Gate("acme", run, inc, name).confirm(FX, evs)
    rows = g.ro_query("MATCH (:Incident {id:$i})-[:HAS_GATE_RUN]->(r:GateRun) RETURN r.passed, r.cause_id", {"i": inc}).result_set
    assert [False, FX] in rows


def test_g4_rejects_a_cause_without_quantitative_evidence_on_its_chain(room):
    """G4: a path alone is not evidence. Confirming with no measurement cited fails G4."""
    g, name, run, inc = room
    investigate(name, run)
    res = Gate("acme", run, inc, name).confirm(CUTOVER, [])
    assert not res.passed and "G4 quantitative" in {c.name for c in res.failed()}


def test_g6_refuses_while_a_competitor_with_a_path_is_still_open(room):
    """G6: an open competitor that also has a path and was never eliminated blocks a confident claim."""
    g, name, run, inc = room
    evs = investigate(name, run)
    writes.inject_change(g, id="D-competitor-test", target="raw.raw_orders", at=ONSET - 8 * 60_000, kind="config",
                         tenant="acme")
    writes.upsert_hypothesis(g, inc=inc, hid=f"hyp-{inc}-comp", cause="D-competitor-test", status="open",
                             reason="also upstream of the KPI", origin="model")
    res = Gate("acme", run, inc, name).confirm(CUTOVER, evs)
    g6 = {c.name: c for c in res.checks}
    assert (not res.passed) or (not res.confident), {c.name: (c.passed, c.detail) for c in res.checks}
    assert any(n.startswith("G6") and g6[n].passed is False for n in g6), {c.name: c.passed for c in res.checks}
