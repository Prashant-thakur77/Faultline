"""Live: warm recall. The second payment incident in the SAME graph (after S1 was resolved and written back)
recalls S1 through the FalkorDB vector index + a shared Symptom node, learns which fix worked, and links
PRECEDENT_FOR at write-back. The cold control (fresh golden copy) cannot recall S1. Memory only reorders the
investigation; the gate still decides."""

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO
from faultline.memory.learn import learn

pytestmark = pytest.mark.live


def _effects(sid, onset):
    return scenario.effects_of(scenario.load(sid), onset)


def _resolve(p, res, hub):
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    # resolve with the flag lever (the procedure this test's derived runbook counts); the learned ordering
    # (Q-REM-1) may put another enabled action first, so pick by kind, not by position
    o = next(o for o in res.post_gate["options"] if o["enabled"] and o["kind"] == "flip_flag")
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom=p.symptoms[0], onset_ms=p.onset_ms, effects=_effects(p.scenario["id"], p.onset_ms),
                   at_ms=p.onset_ms + 5 * 60_000)
    return c, o, v, act.write_back(c, o["id"], cause=res.cause_id, confident=True)


@pytest.fixture
def graphs():
    made: list[str] = []
    yield made
    for g in made:
        gcopy.delete_if_exists(gclient.engine(), g)


def test_cold_s1b_recalls_only_history(graphs):
    p, res = anyio.run(lambda: scenario.run("S1b", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(p.graph)
    assert res.outcome == "CONFIRMED" and res.cause_id == "D-pay-421", res.error
    assert res.recall["precedents"] and all(i.startswith("inc-h") for i in res.recall["precedents"])
    assert "payment" in res.recall["prior"]


def test_warm_s1b_recalls_s1_and_links_precedent(graphs):
    p1, r1 = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(p1.graph)
    assert r1.outcome == "CONFIRMED"
    hub = gh.client(p1.graph)
    _, _, v1, wb1 = _resolve(p1, r1, hub)
    assert v1["verdict"] == "APPLIED" and wb1["verified"] == "7/7"
    # LEARN: S1 joins the payment family (labelPropagation) and strengthens the derived runbook
    lr = learn(p1.tenant, p1.graph, p1.incident_id, p1.run_id)
    assert p1.incident_id in lr["family"] and lr["runbook"]["support"] == 5

    p2, r2 = anyio.run(lambda: scenario.run("S1b", BaselineInvestigator(), set_mode=False, keep=True, graph=p1.graph))
    assert r2.outcome == "CONFIRMED" and r2.cause_id == "D-pay-421", r2.error
    # vector seed + shared symptom: the resolved S1 incident is the top precedent, and it is the most recent
    assert r2.recall["precedents"][0] == p1.incident_id
    ro = RO(p2.tenant, p2.graph)
    top = ro.run("Q-MEM-4", {"inc": p2.incident_id}).rows[0]
    assert top["id"] == p1.incident_id and "sym-error_rate-checkout" in top["shared"]
    assert {"kind": "flip_flag", "verdict": "APPLIED", "target": "paymentGate"} in [
        {k: a[k] for k in ("kind", "verdict", "target")} for a in top["actions"]]
    # warm prior on payment is stronger than anything history alone gave (recency ≈ 1)
    assert r2.recall["prior"]["payment"] > 0.5
    hyp = next(s for s in r2.suspects if s["id"] == "D-pay-421")
    assert hyp["prior"] > 0
    # procedural memory first: the derived runbook (now 5× supported) is the first runbook at RECALL
    assert r2.recall["runbooks"][0] == lr["runbook"]["runbook"]
    # the world says the flag is back on, so the same lever is offered again
    assert any(o["kind"] == "flip_flag" and o["enabled"] for o in r2.post_gate["options"])
    # the fix that worked last time is part of the plan's fix history
    assert any(f["kind"] == "flip_flag" and f["verdict"] == "APPLIED" and p1.incident_id in f["incidents"]
               for f in r2.post_gate["fix_history"])
    # write-back links PRECEDENT_FOR from S1 → S1b (read back through the RO wrapper)
    c2, _, v2, wb2 = _resolve(p2, r2, hub)
    assert v2["verdict"] == "APPLIED" and wb2["verified"] == "7/7"
    assert wb2["precedents"][0] == p1.incident_id
    n = c2.g().ro_query("MATCH (:Incident {id:$a})-[:PRECEDENT_FOR]->(:Incident {id:$b}) RETURN count(*)",
                        {"a": p1.incident_id, "b": p2.incident_id}).result_set[0][0]
    assert n == 1


def test_decay_never_unpins_applied():
    """W-MEM-1: an incident with an APPLIED fix keeps its salience; one without decays by half per half-life.
    (Mutation check: if the APPLIED exemption were dropped, the first assertion fails.)"""
    from faultline.graph import writes

    name = "eval_acme_decay_probe"
    db = gclient.engine()
    gcopy.delete_if_exists(db, name)
    gcopy.copy_graph(db, "golden_acme", name)
    try:
        g = db.select_graph(name)
        g.query("MATCH (i:Incident {id:'inc-h005'}) SET i.last_used = 0, i.salience_base = 1.0")
        g.query("CREATE (:Incident:Node {id:'inc-decay', last_used: 0, salience_base: 1.0, salience: 1.0})")
        out = writes.decay(g, now_ms=30 * 86_400_000, half_life_days=30)
        s = dict(g.ro_query("MATCH (i:Incident) WHERE i.id IN ['inc-h005','inc-decay'] RETURN i.id, i.salience").result_set)
        assert s["inc-h005"] == 1.0
        assert abs(s["inc-decay"] - 0.5) < 1e-6
        assert out["decayed"] == 1
    finally:
        gcopy.delete_if_exists(db, name)


def test_memory_reorders_but_never_changes_the_gate(graphs):
    """Cold (fresh golden) vs warm (after S1 resolved in the same graph): identical gate verdicts, check by check."""
    pc, cold = anyio.run(lambda: scenario.run("S1b", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(pc.graph)
    p1, r1 = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(p1.graph)
    _resolve(p1, r1, gh.client(p1.graph))
    pw, warm = anyio.run(lambda: scenario.run("S1b", BaselineInvestigator(), set_mode=False, keep=True, graph=p1.graph))

    def verdicts(res):
        return (res.outcome, res.cause_id, sorted((c["name"], c["passed"]) for c in res.gate["checks"]),
                sorted((s["change"], s["status"]) for s in res.sweep))

    assert verdicts(cold) == verdicts(warm)
    assert warm.recall["prior"]["payment"] > cold.recall["prior"]["payment"]


def test_s3b_second_scenario_recalls_s3_and_keeps_gate_verdicts(graphs):
    """Second cold-vs-warm scenario (T2 go/no-go needs >= 2): a repeat DB config regression after S3 was resolved."""
    pc, cold = anyio.run(lambda: scenario.run("S3b", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(pc.graph)
    p1, r1 = anyio.run(lambda: scenario.run("S3", BaselineInvestigator(), set_mode=False, keep=True))
    graphs.append(p1.graph)
    c = act.Ctx(p1.tenant, p1.graph, p1.incident_id, p1.run_id)
    hub = gh.client(p1.graph)
    o = next(o for o in r1.post_gate["options"] if o["enabled"] and o["kind"] != "open_issue")
    spec = act.choose(c, o["id"], hub)
    act.approve(c, o["id"], spec["plan_hash"], "p-030")
    act.execute(c, o["id"], hub)
    v = act.verify(c, o["id"], hub, symptom=p1.symptoms, onset_ms=p1.onset_ms,
                   effects=scenario.effects_of(p1.scenario, p1.onset_ms), at_ms=p1.onset_ms + 300_000)
    assert v["verdict"] == "APPLIED" and act.write_back(c, o["id"], cause=r1.cause_id, confident=True)["verified"] == "7/7"
    pw, warm = anyio.run(lambda: scenario.run("S3b", BaselineInvestigator(), set_mode=False, keep=True, graph=p1.graph))
    assert warm.recall["precedents"][0] == p1.incident_id
    assert warm.recall["prior"]["astronomy-db"] > cold.recall["prior"].get("astronomy-db", 0.0)
    assert (cold.outcome, cold.cause_id) == (warm.outcome, warm.cause_id) == ("CONFIRMED", "D-pgcfg-4")
    assert sorted((x["name"], x["passed"]) for x in cold.gate["checks"]) == sorted((x["name"], x["passed"]) for x in warm.gate["checks"])
