"""Live: learned remediation ordering (Q-REM-1) and the advisory residue check (Q-RESIDUE-1) on seeded graphs and
fresh scenario copies. Ordering only permutes the enabled actions; the residue check never changes a gate outcome."""

import anyio
import pytest

from faultline import scenario
from faultline.actions import act
from faultline.actions import github as gh
from faultline.agent import report
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ro(db):
    r = RO("acme")
    try:
        r.require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"acme not seeded: {e}")
    return r


def test_rate_is_beta_smoothed_in_cypher_and_history_needs_a_basis(ro):
    syms = [r["id"] for r in ro.run("Q-INC-SYM", {"inc": "inc-h011"}).rows]
    rows = ro.run("Q-REM-1", {"inc": "", "symptoms": syms, "incidents": []}).rows
    assert rows, "the seeded history resolves incidents sharing this symptom"
    for r in rows:
        assert r["n"] == r["successes"] + r["failures"]
        assert r["rate"] == pytest.approx((r["successes"] + 1) / (r["n"] + 2))
    assert [r["rate"] for r in rows] == sorted((r["rate"] for r in rows), reverse=True)
    assert any(r["failures"] > 0 for r in rows), "the NOT_APPLIED attempt counts as a failure"
    # the incident itself is excluded; no symptoms and no precedents ⇒ no history at all
    own = ro.run("Q-REM-1", {"inc": "inc-h011", "symptoms": syms, "incidents": []}).rows
    assert all("inc-h011" not in r["incidents"] for r in own)
    assert ro.run("Q-REM-1", {"inc": "", "symptoms": [], "incidents": []}).rows == []
    by_prec = ro.run("Q-REM-1", {"inc": "", "symptoms": [], "incidents": ["inc-h011"]}).rows
    assert by_prec and all(r["incidents"] == ["inc-h011"] for r in by_prec)


@pytest.fixture(scope="module")
def s1():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    yield p, res
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_residue_is_advisory_and_reports_what_the_cause_cannot_reach(s1):
    p, res = s1
    assert (res.outcome, res.cause_id) == ("CONFIRMED", "D-pay-417"), res.error
    r = res.residue
    assert r["verdict"] == "residue" and (r["k"], r["n"]) == (3, 4)
    # the eliminated same-minute change had a real (small) effect of its own: measured anomalous, not reachable
    assert r["unexplained"] == ["recommendation"] and "another fault may be active" in r["summary"]
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    assert rep.residue["unexplained"] == ["recommendation"] and rep.outcome == "CONFIRMED" and rep.confident
    assert "Residue check (advisory" in report.to_markdown(rep)


def test_learned_ordering_permutes_enabled_actions_and_the_top_one_verifies(s1):
    p, res = s1
    opts = res.post_gate["options"]
    rem = res.post_gate["remedy"]
    assert rem["applied"] and rem["evidence_id"]
    enabled = [o for o in opts if o["enabled"]]
    assert [o["kind"] for o in enabled][-1] == "open_issue"          # tracking stays after the actions
    assert all(o["enabled"] for o in opts[:len(enabled)])            # enabled-first is never overridden
    assert sorted(o["static_rank"] for o in opts) == list(range(1, len(opts) + 1))  # a permutation, nothing added
    top = opts[0]
    assert top["history"] and "history:" in top["reason"]
    if rem["moved"]:
        assert top["static_rank"] != 1
    # the plan the graph holds is the reordered one, and the reordered top option goes through end to end
    plan = RO(p.tenant, p.graph).run("Q-ACT-1", {"inc": p.incident_id}).rows
    assert [a["kind"] for a in plan] == [o["kind"] for o in opts]
    c, hub = act.Ctx(p.tenant, p.graph, p.incident_id, p.run_id), gh.client(p.graph)
    spec = act.choose(c, top["id"], hub)
    act.approve(c, top["id"], spec["plan_hash"], "p-030")
    act.execute(c, top["id"], hub)
    v = act.verify(c, top["id"], hub, symptom=p.symptoms, onset_ms=p.onset_ms,
                   effects=scenario.effects_of(p.scenario, p.onset_ms), at_ms=p.onset_ms + 5 * 60_000)
    assert v["verdict"] == "APPLIED", v
    assert act.write_back(c, top["id"], cause=res.cause_id, confident=True)["verified"] == "7/7"
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    assert rep.remedy["applied"] and rep.remedy["lines"]


def test_no_history_is_a_no_op_that_says_so():
    p, res = anyio.run(lambda: scenario.run("S3", BaselineInvestigator(), set_mode=False, keep=False))
    assert res.outcome == "CONFIRMED", res.error
    rem = res.post_gate["remedy"]
    assert not rem["applied"] and not rem["moved"] and "no-op" in rem["note"]
    assert [o["static_rank"] for o in res.post_gate["options"]] == list(range(1, len(res.post_gate["options"]) + 1))
    assert res.residue["verdict"] == "explained" and res.residue["k"] == res.residue["n"] > 0
