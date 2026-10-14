"""Futures (M14 #1), the code around the graph: option ordering by predicted future, history kept inside a class,
the prediction-vs-outcome record, VERIFY's shared band rule, the template's lint and the world seed."""

import json

from faultline.actions.act import future_class, order_by_history, prediction_outcome
from faultline.agent.datatools import ABS_TOL, in_band
from faultline.agent.phases import INTERNAL_TOOLS, PHASE_TOOLS
from faultline.agent.state import Stage
from faultline.graph.templates import catalogue, load


def _opt(kind, target, predicted=None, exposed=(), enabled=True):
    o = {"kind": kind, "option": f"{kind} {target}", "target": target, "enabled": enabled, "reason": "r", "args": {"x": 1}}
    if predicted:
        o["future"] = {"predicted": predicted, "exposed": list(exposed), "line": predicted}
    return o


def _row(kind, target, s, f):
    return {"kind": kind, "target": target, "successes": s, "failures": f, "n": s + f, "rate": (s + 1) / (s + f + 2)}


def test_future_class_orders_contains_then_unknown_then_not_and_never_ranks_exposure():
    """Exposure is said, not ranked: an assumed removal (rollback, nothing exposed by construction) must not outrank a
    measured containment on a number it never measured (review 2026-10-13, finding 1)."""
    a = _opt("flip_flag", "F", "contains", ["kpi.x"])
    b = _opt("rollback_deploy", "D", "contains")
    c = _opt("flip_flag", "G", "does_not_contain")
    d = _opt("flip_flag", "H")  # no future read: unknown
    assert sorted([a, b, c, d], key=future_class) == [a, b, d, c]  # stable: a and b keep their static order
    stored = {**a, "future": json.dumps(a["future"])}  # as Q-ACT-1 reads it back (JSON text)
    assert future_class(stored) == future_class(a) == 0


def test_history_never_lifts_an_option_across_a_predicted_future_class():
    """The flag has the better record, but the futures say it will not contain: the rollback stays first."""
    opts = [_opt("rollback_deploy", "D", "contains"), _opt("flip_flag", "F", "does_not_contain"),
            _opt("open_issue", "D", "does_not_contain")]
    rem = {"rows": [_row("rollback_deploy", "*", 1, 3), _row("flip_flag", "F", 9, 0)], "basis": "b"}
    out = order_by_history(opts, rem, min_n=2)
    assert [o["kind"] for o in out] == ["rollback_deploy", "flip_flag", "open_issue"]
    assert out[1]["history"]["successes"] == 9  # the history is still said, it just does not cross the class
    same = [_opt("rollback_deploy", "D", "contains"), _opt("flip_flag", "F", "contains")]
    assert [o["kind"] for o in order_by_history(same, rem, min_n=2)] == ["flip_flag", "rollback_deploy"]  # within a class


def test_without_futures_history_ordering_is_unchanged():
    opts = [_opt("flip_flag", "F"), _opt("rollback_deploy", "D")]
    rem = {"rows": [_row("rollback_deploy", "*", 7, 1), _row("flip_flag", "F", 2, 2)], "basis": "b"}
    assert [o["kind"] for o in order_by_history(opts, rem, min_n=2)] == ["rollback_deploy", "flip_flag"]


def test_prediction_outcome_compares_the_symptoms_own_band_only():
    """`observed` is the symptoms' plain band with the change at main (verify computes it); a NOT_APPLIED for
    collateral or a change missing at main reaches here as None, never as a failed containment."""
    f = json.dumps({"predicted": "contains", "key": "a|b", "evidence_id": "ev_1"})
    assert prediction_outcome(f, "flip_flag", "contains") == {
        "predicted": "contains", "observed": "contains", "agrees": True, "assumed": False, "key": "a|b",
        "evidence_id": "ev_1"}
    assert prediction_outcome(f, "flip_flag", "does_not_contain")["agrees"] is False
    assert prediction_outcome({"predicted": "does_not_contain"}, "rollback_deploy", "does_not_contain")["agrees"] is True
    assert prediction_outcome({"predicted": "contains", "assumed": True}, "rollback_deploy", "contains")["assumed"] is True
    assert prediction_outcome(f, "flip_flag", None) is None               # UNKNOWN, or not at main: nothing observed
    assert prediction_outcome(f, "open_issue", "contains") is None        # an issue tracks; it does not contain
    assert prediction_outcome({"predicted": "unknown"}, "flip_flag", "contains") is None
    assert prediction_outcome(None, "flip_flag", "contains") is None


def test_in_band_is_verifys_rule():
    assert in_band(0.0105, 0.01, 1.1) and not in_band(0.02, 0.01, 1.1)
    assert in_band(0.002 + ABS_TOL * 0.99, 0.002, 1.0)                    # the absolute floor
    assert in_band(0.03, 0.01, 1.1, allowance=0.02) and not in_band(0.03, 0.01, 1.1, allowance=0.005)


def test_futures_template_is_linted_and_reads_measured_excess_only():
    q = load("Q-FUTURE-1").text
    assert "MetricWindow" in q and "$removes_origin" in q and "PROPAGATES_TO*1..8" in q
    assert "error_rate:" not in q and "Effect" not in q   # the prediction never sees the scenario's injected effects
    assert "Q-MEM-6P" in catalogue()


def test_futures_is_an_internal_contain_tool():
    assert "futures" in PHASE_TOOLS[Stage.CONTAIN] and "futures" in INTERNAL_TOOLS
