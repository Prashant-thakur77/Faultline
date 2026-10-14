"""Live (M12): the incident-time additions on the hero S1, each checked against a direct read of the same graph.
Who to notify (Q-NOTIFY-1), why alerts missed it (Q-CHAIN-MON), ownership when the change shipped (Q-OWN-AT) and the
"possible missing edge" note for a suspect G2 rejected (Q-COUPLE-1). Grading literals live here, never in the product."""

import anyio
import pytest

from faultline import scenario
from faultline.agent import report
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def s1(db):
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    assert res.outcome == "CONFIRMED" and res.post_gate
    yield p, res
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_notify_set_matches_owners_and_oncall_read_directly(s1):
    p, res = s1
    notify = res.post_gate["notify"]
    assert notify, "nobody to notify for a checkout-breaking payment fault"
    g = gclient.engine().select_graph(p.graph)
    for row in notify:
        # the on-call list must equal a direct ON_CALL read at onset (engine bug #11 once emptied it silently)
        direct = sorted(r[0] for r in g.ro_query(
            "MATCH (x:Person)-[oc:ON_CALL]->(t:Team {id:$t}) WHERE oc.from <= $now AND $now < oc.to AND x.active "
            "RETURN DISTINCT x.id", {"t": row["team"], "now": p.onset_ms}).result_set)
        assert sorted(row["oncall"]) == direct, row
        owned = {r[0] for r in g.ro_query("MATCH (:Team {id:$t})-[:OWNS]->(n) RETURN n.id", {"t": row["team"]}).result_set}
        assert set(row["owns_impacted"]) <= owned and "payment" not in row["owns_impacted"]  # impacted, not the origin
    checkout = next(r for r in notify if "checkout" in r["owns_impacted"])
    assert checkout["oncall"] and checkout["nearest_hops"] == 1
    assert [r["impact"] for r in notify] == sorted((r["impact"] for r in notify), reverse=True)


def test_alert_coverage_reports_the_first_alerted_hop(s1):
    p, res = s1
    tok = context.bind(p.tenant, graph=p.graph)
    try:
        out = T.alert_coverage(chain=list(res.gate["chain"]), since=p.onset_ms - 30 * 60_000, until=p.onset_ms + 10 * 60_000)
    finally:
        context.unbind(tok)
    hops = {h["id"]: h for h in out["rows"]}
    assert [h["id"] for h in out["rows"]] == list(res.gate["chain"])
    sym = lambda h: [a for a in h["alerts"] if a["metric"] != "slo_burn"]  # noqa: E731  (symptom alerts)
    assert sym(hops["checkout"]) and not sym(hops["payment"])                     # no symptom alert on the origin …
    burn = [a for a in hops["payment"]["alerts"] if a["metric"] == "slo_burn"]
    assert burn and burn[0]["at"] < p.onset_ms                                   # … but its SLO-burn page fired first
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    assert rep.why_alerts_missed_it["summary"].startswith("first alert at hop")
    assert "D-pay-417" in rep.why_alerts_missed_it["summary"]                    # the change itself is the silent hop
    tok = context.bind(p.tenant, graph=p.graph)
    try:
        assert "error" in T.alert_coverage(chain=["x"] * 21, since=0, until=1)  # too long: refused, not truncated
        assert "error" in T.alert_coverage(chain=["payment"], since=2, until=1)
    finally:
        context.unbind(tok)


def test_report_ownership_when_the_change_shipped(s1):
    p, res = s1
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    own = rep.ownership
    assert own["component"] == "payment" and own["owner_then"] == own["owner_now"] == "team-payments"
    assert not own["changed_hands"] and "Ownership when the change shipped" in report.to_markdown(rep)
    assert res.post_gate["owner_at_change"]["owner_then"] == "team-payments"


def test_missing_edge_note_only_for_a_g2_rejected_suspect_with_co_failure_history(s1):
    p, res = s1
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    assert not any("missing edge" in i.claim for i in rep.inferred)              # no recommendation→checkout history
    branch = f"{p.graph}_hist"
    gcopy.copy_graph(gclient.engine(), p.graph, branch)
    try:
        g = gclient.engine().select_graph(branch)
        for k in range(3):  # test-only history on a throwaway branch: incidents caused at recommendation that hit checkout
            g.query("MATCH (r:Node {id:'recommendation'}), (c:Node {id:'checkout'}) "
                    "CREATE (i:Incident:Node {id:$i, opened_at: 0}) "
                    "CREATE (i)-[:AFFECTED {role:'cause', key:'cause'}]->(r), (i)-[:AFFECTED {role:'impacted', key:'impacted'}]->(c)",
                    {"i": f"inc-test-cpl-{k}"})
        rep2 = report.build(p.tenant, branch, p.incident_id, res.outcome)
        notes = [i for i in rep2.inferred if "missing edge" in i.claim]
        assert len(notes) == 1 and "recommendation → checkout" in notes[0].claim and "D-rec-12" in notes[0].basis
        assert rep2.outcome == rep.outcome and rep2.cause_id == rep.cause_id      # a note, never a verdict change
    finally:
        gcopy.delete_if_exists(gclient.engine(), branch)


def test_slo_burn_pages_fire_in_the_world_but_are_not_symptoms(s1):
    """§4.1: the simulator's monitoring raises an slo_burn page when the trailing burn crosses obligation.fast_burn.
    INTAKE (Q-ALERT-1) takes symptoms from symptom alerts only, so the hero still investigates checkout/frontend."""
    p, res = s1
    g = gclient.engine().select_graph(p.graph)
    burns = {r[0] for r in g.ro_query("MATCH (a:Alert {metric:'slo_burn'})-[:FIRED_ON]->(n) RETURN n.id").result_set}
    assert "payment" in burns and "checkout" in burns
    assert sorted(p.symptoms) == ["checkout", "frontend"]
