"""Obligation clock (M12), unit level (no FalkorDB): the time-to-breach arithmetic on template rows, the urgency
verdict at the weights.yaml paging line, the escalation urgency (a failed clock is unknown, never "not urgent"),
the brain routing, and that the tool fails loudly when the graph is off."""

import pytest

from faultline.agent.loop import obligation_urgency
from faultline.agent.weights import weights
from faultline.brain.ask import _intent
from faultline.mcp_server import tools as T

W = {"current_min": 3, "sustainable_burn": 1.0, "page_within_min": 1440}


def _slo(slo="slo-a", burn=30.0, remaining=0.5, window_days=30, service="a"):
    return {"slo": slo, "service": service, "burn": burn, "budget_remaining": remaining, "window_days": window_days,
            "error_rate": None if burn is None else burn * 0.01}


def test_weights_section_exists_with_reasons():
    w = weights()["obligation"]
    assert set(w) == {"current_min", "sustainable_burn", "page_within_min", "fast_burn", "burn_window_min"}
    from faultline.agent.weights import WEIGHTS_PATH

    body = WEIGHTS_PATH.read_text().split("\nobligation:", 1)[1]
    assert all("#" in line for line in body.strip().splitlines()[:5])  # every coefficient carries its one-line reason


def test_breach_minutes_is_remaining_window_over_burn():
    # 50% of a 30-day budget left at 30x burn: 0.5 × 43 200 min / 30 = 720 min
    assert T.breach_minutes(_slo(burn=30.0, remaining=0.5), W) == 720.0
    assert T.breach_minutes(_slo(burn=60.0, remaining=0.5), W) == 360.0       # twice the burn, half the time
    assert T.breach_minutes(_slo(burn=30.0, remaining=-0.1), W) == 0.0        # already spent and still burning
    assert T.breach_minutes(_slo(burn=1.0, remaining=0.5), W) is None         # sustainable: no breach projected
    assert T.breach_minutes(_slo(burn=0.4, remaining=0.5), W) is None
    assert T.breach_minutes(_slo(burn=None, remaining=0.5), W) is None        # no current telemetry: never guessed


def test_slo_status():
    assert T.slo_status(_slo(burn=None), W) == "unmeasured"
    assert T.slo_status(_slo(burn=30.0), W) == "burning"
    assert T.slo_status(_slo(burn=0.5), W) == "within_budget"
    assert T.slo_status(_slo(burn=0.5, remaining=0.0), W) == "breached"


def test_verdict_flips_at_the_paging_line():
    slos = [{**_slo("slo-a", 30.0, 0.5), "breach_in_min": 720.0}, {**_slo("slo-b", 2.0, 0.5, service="b"), "breach_in_min": 10800.0}]
    cust = [{"customer": "c1", "revenue_at_risk": 21000.0, "customers_reached": 2}]
    v = T.clock_verdict(slos, cust, W)
    assert v["urgent"] and v["breach"]["slo"] == "slo-a" and v["breach"]["breach_in_min"] == 720.0
    assert v["revenue_at_risk"] == 21000.0 and v["customers_reached"] == 2
    assert "under the 1440-min paging line" in v["reason"] and "21,000 MRR" in v["reason"]
    assert not T.clock_verdict(slos, cust, {**W, "page_within_min": 720})["urgent"]   # strictly under the line
    assert T.clock_verdict(slos, cust, {**W, "page_within_min": 721})["urgent"]


def test_verdict_without_a_projected_breach_is_not_urgent_and_says_why():
    v = T.clock_verdict([{**_slo(burn=0.5), "breach_in_min": None}], [], W)
    assert v["urgent"] is False and v["breach"] is None and "no SLO" in v["reason"]
    mixed = [{**_slo(burn=0.5), "breach_in_min": None}, {**_slo("slo-b", burn=None), "breach_in_min": None}]
    v = T.clock_verdict(mixed, [], W)
    assert v["urgent"] is False and "1 of 2 unmeasured" in v["reason"]


def test_every_slo_unmeasured_is_unknown_not_quiet():
    """No current telemetry for any SLO is "unknown", never "nothing burning" (review finding)."""
    v = T.clock_verdict([{**_slo(burn=None), "breach_in_min": None}, {**_slo("slo-b", burn=None), "breach_in_min": None}], [], W)
    assert v["urgent"] is None and v["reason"].startswith("unmeasured") and "burning" not in v["reason"]
    u = obligation_urgency({**v, "evidence_id": "ev_1"})
    assert u["urgent"] is None and u["reason"].startswith("unmeasured")                # the loop keeps it unknown
    v = T.clock_verdict([], [], W)
    assert not v["urgent"] and "no SLO covers" in v["reason"] and v["customers_reached"] == 0


def test_escalation_urgency_from_the_clock():
    u = obligation_urgency({"urgent": True, "reason": "r", "page_within_min": 1440.0, "breach": {"slo": "s"},
                            "evidence_id": "ev_1"})
    assert u == {"urgent": True, "reason": "r", "page_within_min": 1440.0, "breach": {"slo": "s"}, "evidence_id": "ev_1"}
    bad = obligation_urgency({"error": "unavailable: graph disabled (FAULTLINE_DISABLE_GRAPH=true)"})
    assert bad["urgent"] is None and "obligation clock unavailable" in bad["reason"]   # unknown, never "not urgent"


def test_tool_fails_loudly_when_the_graph_is_disabled(monkeypatch):
    from faultline.config import settings

    monkeypatch.setattr(settings, "faultline_disable_graph", True)
    out = T.obligation_clock(target_id="payment", now=1_792_033_200_000)
    assert "error" in out and "disabled" in out["error"] and "rows" not in out


@pytest.mark.parametrize("args", [{"target_id": "", "now": 1}, {"target_id": "x", "now": -1},
                                  {"target_id": "x", "now": 5_000_000_000_000}, {"target_id": "x" * 161, "now": 1}])
def test_tool_validates_inputs(args):
    out = T.obligation_clock(**args)
    assert out["error"].startswith("invalid arguments")


def test_brain_routes_obligation_questions():
    assert _intent("Which customers are affected if checkout goes down?") == "obligations"
    assert _intent("What SLOs depend on payment?") == "obligations"
    assert _intent("How much revenue at risk if cart fails?") == "obligations"
    assert _intent("What breaks if payment goes down?") == "blast"          # unchanged
    assert _intent("Who has worked on stg_customers?") == "people"           # a table name is not a customer question
    assert _intent("What did we decide about customer emails?") == "decision"
