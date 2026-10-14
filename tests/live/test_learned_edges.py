"""Live, M15 #4: a verified fix teaches the graph a missing failure link; nothing else does.
A bench world whose cause → symptom path has one edge hidden from the graph: the gate abstains. A human-named rollback
of the WRONG change verifies NOT_APPLIED and teaches nothing; of the right change it verifies APPLIED, the product
proposes the missing link with the measured share, and only an approval of that exact proposal writes the edge."""

import sys
import uuid
from pathlib import Path

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent.loop import BaselineInvestigator, run_incident
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.tenant import eval_graph
from faultline.memory import edges

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
import gate_bench  # noqa: E402
import learning_eval  # noqa: E402

pytestmark = pytest.mark.live
CASE = "gb009"  # its decoy has NO path to the symptom: an unverified learner would invent one


@pytest.fixture
def abstained():
    case = next(c for c in gate_bench.generate(seed=20261015) if c["id"] == CASE)
    p = scenario.prepare(case["spec"]["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=case["spec"])
    hide = learning_eval._hidden_edge(p, case)
    world = eval_graph(p.tenant, f"w{uuid.uuid4().hex[:6]}", "world", "bench", 1)
    gcopy.copy_graph(client.engine(), p.graph, world)   # the true world, apart from the wrong graph
    p.world = world
    writes.perturb_model(client.engine().select_graph(p.graph), delete=[list(hide)])
    r = anyio.run(lambda: run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms, symptoms=p.symptoms,
                                       investigator=BaselineInvestigator(), graph=p.graph, run_id=p.run_id, window_min=30))
    assert r.cause_id is None or r.outcome != "CONFIRMED"     # the gate abstains on the wrong graph
    c = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id)
    hub = gh.client(p.graph)
    act.ensure_infra_repo(c, hub)
    yield p, case, c, hub
    gcopy.delete_if_exists(client.engine(), p.graph)
    gcopy.delete_if_exists(client.engine(), world)


def _fix(p, c, hub, change):
    opt = edges.human_fix_option(c, change=change, by="p-030", why="test")
    spec = act.choose(c, opt["id"], hub)
    act.approve(c, opt["id"], spec["plan_hash"], "p-030")
    act.execute(c, opt["id"], hub)
    v = act.verify(c, opt["id"], hub, symptom=p.symptoms, onset_ms=p.onset_ms,
                   effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 300_000,
                   world_seed=int(p.scenario.get("seed", 42)), world_graph=p.world)
    return opt["id"], v["verdict"]


def _learned(p):
    return client.engine().select_graph(p.graph).ro_query(
        "MATCH (a)-[e:PROPAGATES_TO]->(b) WHERE e.learned RETURN a.id, b.id, e.cap").result_set


def test_a_wrong_human_guess_verifies_not_applied_and_teaches_nothing(abstained):
    p, case, c, hub = abstained
    decoy = next(d for d, why in sorted(case["expected"]["eliminated"].items()) if why.startswith("G2"))
    aid, verdict = _fix(p, c, hub, decoy)
    assert verdict == "NOT_APPLIED"
    assert edges.propose(c, aid, onset_ms=p.onset_ms, symptoms=p.symptoms) == [] and _learned(p) == []


def test_a_verified_fix_proposes_the_link_and_only_its_exact_approval_writes_it(abstained):
    p, case, c, hub = abstained
    aid, verdict = _fix(p, c, hub, case["expected"]["cause"])
    assert verdict == "APPLIED"
    props = edges.propose(c, aid, onset_ms=p.onset_ms, symptoms=p.symptoms)
    assert len(props) == 1 and props[0]["dst"] == case["symptom"] and 0 < props[0]["cap"] <= 1
    assert _learned(p) == []                                         # a proposal is not an edge
    assert not edges.approve(c, props[0]["id"], "0" * 64, "p-030")   # another hash approves nothing
    assert edges.approve(c, props[0]["id"], props[0]["plan_hash"], "p-030")
    assert _learned(p) == [[props[0]["src"], props[0]["dst"], props[0]["cap"]]]
    assert not edges.approve(c, props[0]["id"], props[0]["plan_hash"], "p-030")   # once


def test_approval_re_checks_at_write_time(abstained):
    """Prejudge 2026-10-13: approving re-checks, in the same query, that the graph still has no path (a link that
    appeared in the meantime makes the proposal moot) and that the approver is an active person."""
    p, case, c, hub = abstained
    aid, verdict = _fix(p, c, hub, case["expected"]["cause"])
    assert verdict == "APPLIED"
    prop = edges.propose(c, aid, onset_ms=p.onset_ms, symptoms=p.symptoms)[0]
    assert not edges.approve(c, prop["id"], prop["plan_hash"], "nobody-real")      # not an active person
    writes.perturb_model(client.engine().select_graph(p.graph), add=[[prop["src"], prop["dst"], 0.5]])
    assert not edges.approve(c, prop["id"], prop["plan_hash"], "p-030")             # a path exists now
    assert _learned(p) == []


def test_a_proof_that_uses_a_learned_link_says_so(abstained):
    """Prejudge 2026-10-13: a learned shortcut must not look like a real call in the proof path."""
    from faultline.mcp_server import context
    from faultline.mcp_server import tools as T

    p, case, c, hub = abstained
    aid, _ = _fix(p, c, hub, case["expected"]["cause"])
    prop = edges.propose(c, aid, onset_ms=p.onset_ms, symptoms=p.symptoms)[0]
    assert edges.approve(c, prop["id"], prop["plan_hash"], "p-030")
    tok = context.bind(p.tenant, run_id=None, graph=p.graph, record=False)
    try:
        out = T.causal_paths(from_id=case["expected"]["cause"], to_id=prop["dst"])
    finally:
        context.unbind(tok)
    assert out["learned_hops"] == [{"from": prop["src"], "to": prop["dst"], "incident": p.incident_id}]
    assert f"(learned link: {prop['src']} → {prop['dst']} from {p.incident_id})" in out["via"]
