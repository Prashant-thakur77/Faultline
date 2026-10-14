"""Live (M12): the obligation clock on the hero S1, each number checked against a direct read of the same graph.
The checkout SLO burns from the MetricWindow telemetry; customers are reached through checkout and frontend; a
customer reached by two paths counts once; urgency flips at the weights.yaml paging line and decides who is told
first; the report says it; with the graph off the clock errors loudly. Grading literals live here, never in the
product."""

import anyio
import pytest

from faultline import scenario
from faultline.agent import report
from faultline.agent.loop import BaselineInvestigator, obligation_urgency
from faultline.agent.weights import weights
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


def _clock(p, target="payment"):
    tok = context.bind(p.tenant, graph=p.graph)
    try:
        return T.obligation_clock(target_id=target, now=p.onset_ms)
    finally:
        context.unbind(tok)


def test_checkout_slo_burn_matches_the_telemetry(s1):
    p, res = s1
    out = _clock(p)
    assert out["template"] == "Q-OBL-SLO+Q-OBL-CUST" and not out["truncated"]
    slos = {r["service"]: r for r in out["rows"]}
    assert "checkout" in slos and "payment" in slos             # the failing component's own SLO counts too
    assert "product-catalog" not in slos                         # not reachable from payment
    c = slos["checkout"]
    g = gclient.engine().select_graph(p.graph)
    w = weights()["obligation"]
    vals = [r[0] for r in g.ro_query(
        "MATCH (m:MetricWindow {target_id:'checkout', metric:'error_rate', kind:'live'}) WHERE m.at >= $a AND m.at <= $b "
        "RETURN m.value", {"a": p.onset_ms - int(w["current_min"]) * 60_000, "b": p.onset_ms}).result_set]
    assert vals and c["current_windows"] == len(vals)
    assert c["error_rate"] == pytest.approx(sum(vals) / len(vals))
    assert c["burn"] == pytest.approx(c["error_rate"] / c["budget"])
    seen = [r[0] for r in g.ro_query("MATCH (m:MetricWindow {target_id:'checkout', kind:'live'}) WHERE m.at <= $b "
                                     "RETURN m.value", {"b": p.onset_ms}).result_set]
    assert c["budget_remaining"] == pytest.approx(1 - c["spent_prior"] - sum(seen) / (c["budget"] * 30 * 1440))
    assert c["status"] == "burning" and c["breach_in_min"] == pytest.approx(
        c["budget_remaining"] * 30 * 1440 / c["burn"], abs=0.1)


def test_customers_reached_through_checkout_and_frontend_counted_once(s1):
    p, _ = s1
    out = _clock(p)
    cust = {r["customer"]: r for r in out["customers"]}
    assert len(cust) == len(out["customers"]) == out["customers_reached"]   # one row per distinct customer
    reached_via = {n for r in out["customers"] for n in r["through"]}
    assert {"checkout", "frontend"} <= reached_via
    two = [r for r in out["customers"] if set(r["through"]) >= {"checkout", "frontend"}]
    assert two and all(r["paths"] == 2 for r in two)                          # two paths, one row
    assert all(r["path"][0] == "payment" and r["path"][-1] in r["through"] for r in out["customers"])
    assert out["revenue_at_risk"] == pytest.approx(sum(r["mrr"] for r in out["customers"]))  # MRR once per customer
    # direct read: every customer consuming something the failure reaches, and nothing else
    g = gclient.engine().select_graph(p.graph)
    reach = {r[0] for r in g.ro_query("MATCH (s:Node {id:'payment'})-[:PROPAGATES_TO*0..8]->(n) RETURN DISTINCT n.id").result_set}
    direct = {r[0] for r in g.ro_query("MATCH (c:Customer)-[:CONSUMES]->(n) WHERE n.id IN $ids RETURN DISTINCT c.id",
                                       {"ids": sorted(reach)}).result_set}
    assert set(cust) == direct and len(direct) < g.ro_query("MATCH (c:Customer) RETURN count(c)").result_set[0][0]


def test_post_gate_urgency_and_notify_order(s1):
    p, res = s1
    pg = res.post_gate
    assert pg["urgency"]["urgent"] is True and "slo-" in pg["urgency"]["reason"]
    assert pg["urgency"]["breach"]["breach_in_min"] < pg["urgency"]["page_within_min"]
    assert pg["obligations"]["customers_reached"] >= 2 and pg["obligations"]["slos"]
    notify = pg["notify"]
    assert all("priority" in r for r in notify)                      # urgent → owners of obligated nodes first
    flags = [bool(r["priority"]) for r in notify]
    assert flags == sorted(flags, reverse=True)
    assert next(r for r in notify if "checkout" in r["owns_impacted"])["priority"] == ["checkout"]


def test_urgency_flips_at_the_paging_line_and_changes_the_notify_order(s1, monkeypatch):
    p, _ = s1
    m = _clock(p)["breach"]["breach_in_min"]
    monkeypatch.setitem(weights()["obligation"], "page_within_min", m)         # not strictly under: no page
    calm = _clock(p)
    assert calm["urgent"] is False and obligation_urgency(calm)["urgent"] is False
    monkeypatch.setitem(weights()["obligation"], "page_within_min", m + 1)
    hot = _clock(p)
    assert hot["urgent"] is True and obligation_urgency(hot)["urgent"] is True
    tok = context.bind(p.tenant, graph=p.graph)
    try:  # the decision it drives: with a page, teams owning obligated nodes are told first
        plain = T.notify_set(target_id="payment", now=p.onset_ms)
        first = T.notify_set(target_id="payment", now=p.onset_ms, priority_ids=hot["obligated"])
        # a team owning nothing obligated, ranked by impact above an obligated one, must drop below it
        fake = [n for n in hot["obligated"] if n not in plain["rows"][0]["owns_impacted"]]
        moved = T.notify_set(target_id="payment", now=p.onset_ms, priority_ids=fake)
    finally:
        context.unbind(tok)
    assert "priority" not in plain["rows"][0]
    assert {r["team"] for r in plain["rows"]} == {r["team"] for r in first["rows"]}      # reorders, never adds
    assert moved["rows"][0]["team"] != plain["rows"][0]["team"] and moved["rows"][0]["priority"]


def test_report_says_obligations_at_risk(s1):
    p, res = s1
    rep = report.build(p.tenant, p.graph, p.incident_id, res.outcome)
    o = rep.obligations
    assert o["urgent"] is True and any(s["service"] == "checkout" for s in o["slos"])
    md = report.to_markdown(rep)
    assert "## Obligations at risk" in md and "URGENT: page now" in md and "`slo-checkout`" in md
    assert "each counted once" in md and "MRR at risk" in md


def test_the_clock_errors_loudly_with_the_graph_off(s1, monkeypatch):
    from faultline.config import settings

    p, _ = s1
    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    out = _clock(p)
    assert "error" in out and "disabled" in out["error"] and "rows" not in out
    assert obligation_urgency(out)["urgent"] is None
