"""Unit (no FalkorDB): learned remediation ordering only permutes the enabled actions; the residue check counts what
the graph returned. The numbers (rates) come from Q-REM-1 rows; this code only orders and phrases them."""

import pytest

from faultline.actions.act import BETA_PRIOR, order_by_history, remedy_summary
from faultline.graph.ro import QueryResult
from faultline.graph.templates import load
from faultline.mcp_server import context
from faultline.mcp_server import tools as T


def _opts():
    # the static order build_options produces: enabled actions, then open_issue, then disabled ones
    return [
        {"kind": "flip_flag", "option": "flag F → off", "target": "F", "enabled": True, "reason": "cuts a → b", "args": {"x": 1}},
        {"kind": "rollback_deploy", "option": "roll back D", "target": "D", "enabled": True, "reason": "revert D", "args": {}},
        {"kind": "open_issue", "option": "open an issue", "target": "D", "enabled": True, "reason": "track", "args": {}},
        {"kind": "data_repair", "option": "repair", "target": "D", "enabled": False, "reason": "needs a patch", "args": {}},
    ]


def _row(kind, target, s, f):
    return {"kind": kind, "target": target, "successes": s, "failures": f, "n": s + f, "rate": (s + 1) / (s + f + 2),
            "incident_count": s + f, "incidents": []}


def _remedy(*rows, basis="past incidents sharing a symptom with this one"):
    return {"rows": list(rows), "basis": basis, "evidence_id": "ev_test"}


def _same_set(a, b):
    key = lambda o: (o["kind"], o["target"], o["enabled"], o["option"])  # noqa: E731
    return sorted(map(key, a)) == sorted(map(key, b))


def test_no_history_is_a_no_op_and_says_so():
    static = _opts()
    for remedy in (None, _remedy(), {"error": "unavailable: graph disabled (FAULTLINE_DISABLE_GRAPH=true)"}):
        out = order_by_history(static, remedy, min_n=2)
        assert [o["kind"] for o in out] == [o["kind"] for o in static]
        assert [o["reason"] for o in out] == [o["reason"] for o in static]
        assert all(o["history"] is None for o in out)
        s = remedy_summary(remedy, out)
        assert s["applied"] is False and s["moved"] is False and "static order" in s["note"]


def test_history_reorders_enabled_actions_only_with_a_reason_line():
    static = _opts()
    rem = _remedy(_row("rollback_deploy", "*", 7, 1), _row("flip_flag", "*", 2, 2), _row("flip_flag", "F", 2, 2),
                  _row("data_repair", "*", 9, 0), _row("open_issue", "*", 9, 0))
    out = order_by_history(static, rem, min_n=2)
    assert [o["kind"] for o in out] == ["rollback_deploy", "flip_flag", "open_issue", "data_repair"]
    assert _same_set(out, static)                               # never adds or removes, never enables
    assert out[3]["enabled"] is False and out[3]["history"] is None  # a disabled option is never promoted
    assert out[2]["history"] is None                            # open_issue (tracking) stays after the actions
    assert "rollback worked 7/8 times on past incidents sharing a symptom" in out[0]["reason"]
    assert out[0]["reason"].startswith("revert D; ")           # the original reason is kept
    assert out[1]["history"]["target"] == "F" and "flag F → off worked 2/4" in out[1]["reason"]
    s = remedy_summary(rem, out)
    assert s["applied"] and s["moved"] and s["evidence_id"] == "ev_test" and len(s["lines"]) == 2
    assert [o["static_rank"] for o in out] == [2, 1, 3, 4]


def test_flag_specific_history_wins_over_the_kind_row():
    rem = _remedy(_row("flip_flag", "*", 1, 5), _row("flip_flag", "F", 5, 0), _row("rollback_deploy", "*", 3, 1))
    out = order_by_history(_opts(), rem, min_n=2)
    assert out[0]["kind"] == "flip_flag" and out[0]["history"]["successes"] == 5
    assert remedy_summary(rem, out)["moved"] is False and "agree with the static order" in remedy_summary(rem, out)["note"]


def test_below_min_n_keeps_the_prior_and_ties_keep_the_static_order():
    rem = _remedy(_row("rollback_deploy", "*", 1, 0))          # n=1 < min_n: not used
    out = order_by_history(_opts(), rem, min_n=2)
    assert [o["kind"] for o in out][:2] == ["flip_flag", "rollback_deploy"] and out[1]["history"] is None
    # a known-bad fix (rate < prior) drops below an untried one; an untried one sits at the prior mean
    rem = _remedy(_row("flip_flag", "F", 0, 3))
    out = order_by_history(_opts(), rem, min_n=2)
    assert [o["kind"] for o in out][:2] == ["rollback_deploy", "flip_flag"] and (0 + 1) / (3 + 2) < BETA_PRIOR
    # equal rates: the static order stands
    rem = _remedy(_row("flip_flag", "F", 3, 1), _row("rollback_deploy", "*", 3, 1))
    assert [o["kind"] for o in order_by_history(_opts(), rem, min_n=2)][:2] == ["flip_flag", "rollback_deploy"]


def test_min_n_default_comes_from_weights_yaml():
    from faultline.agent.weights import weights

    assert int(weights()["remedy"]["min_n"]) >= 1
    rem = _remedy(_row("rollback_deploy", "*", 50, 0))
    assert order_by_history(_opts(), rem)[0]["kind"] == "rollback_deploy"


def test_templates_are_linted_and_compute_the_rate_in_cypher():
    rem, res = load("Q-REM-1"), load("Q-RESIDUE-1")
    assert "(toFloat(successes) + 1.0) / (toFloat(successes + failures) + 2.0) AS rate" in rem.display
    assert rem.seen == ("incidents",) and res.seen == ("id",)
    assert "*1..8" in res.display and "e.anomalous = true" in res.display  # bounded; the gate's own measurements
    assert rem.limit <= 100 and res.limit <= 100


class _FakeRO:
    def __init__(self, rows, truncated=False):
        self.rows, self.truncated, self.calls = rows, truncated, []

    def run(self, tid, params):
        self.calls.append((tid, params))
        return QueryResult(tid, load(tid).display, params, list(self.rows[0].keys()) if self.rows else [], list(self.rows),
                           1.0, "d" * 16, set(), self.truncated, "fake")


@pytest.fixture
def unbound():
    tok = context.bind("acme", record=False)
    yield
    context.unbind(tok)


def test_residue_check_counts_explained_and_lists_the_rest(monkeypatch, unbound):
    rows = [{"id": "a", "label": "Service", "evidence": ["ev1"], "kinds": ["error_rate"], "explained": True},
            {"id": "b", "label": "Service", "evidence": ["ev2"], "kinds": ["error_rate"], "explained": True},
            {"id": "z", "label": "Service", "evidence": ["ev3"], "kinds": ["error_rate"], "explained": False}]
    fake = _FakeRO(rows)
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.residue_check(incident_id="inc-x", cause_id="D-x")
    assert fake.calls == [("Q-RESIDUE-1", {"inc": "inc-x", "cause": "D-x"})]
    assert out["advisory"] is True and out["verdict"] == "residue" and (out["k"], out["n"]) == (2, 3)
    assert out["unexplained"] == ["z"] and "explains 2 of 3" in out["summary"] and "another fault may be active: z" in out["summary"]
    assert out["cypher"] and out["evidence_id"].startswith("ev_")


def test_residue_check_all_explained_and_empty(monkeypatch, unbound):
    monkeypatch.setattr(T, "_ro", lambda: _FakeRO([{"id": "a", "label": "Service", "evidence": [], "kinds": [], "explained": True}]))
    assert T.residue_check(incident_id="i", cause_id="c")["verdict"] == "explained"
    monkeypatch.setattr(T, "_ro", lambda: _FakeRO([]))
    out = T.residue_check(incident_id="i", cause_id="c")
    assert out["verdict"] == "no_measurements" and out["n"] == 0


def test_remedy_stats_defaults_to_the_incident_symptoms(monkeypatch, unbound):
    class RO2(_FakeRO):
        def run(self, tid, params):
            self.calls.append((tid, params))
            rows = [{"id": "sym-1", "kind": "error_rate", "target": "t"}] if tid == "Q-INC-SYM" else \
                [_row("rollback_deploy", "*", 3, 0)]
            return QueryResult(tid, load(tid).display, params, list(rows[0]), rows, 1.0, "d" * 16, set(), False, "fake")

    fake = RO2([])
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.remedy_stats(incident_id="inc-x")
    assert [c[0] for c in fake.calls] == ["Q-INC-SYM", "Q-REM-1"]
    assert fake.calls[1][1] == {"inc": "inc-x", "symptoms": ["sym-1"], "incidents": []}
    assert out["rows"][0]["kind"] == "rollback_deploy" and "precedents" not in out["basis"]
    out = T.remedy_stats(incident_id="inc-x", symptom_ids=[], incident_ids=["inc-p"])
    assert fake.calls[-1] == ("Q-REM-1", {"inc": "inc-x", "symptoms": [], "incidents": ["inc-p"]})
    assert "precedents" in out["basis"]
    assert "error" in T.remedy_stats(incident_id="inc-x", symptom_ids=[f"s{i}" for i in range(21)])


def test_post_verdict_tools_are_not_offered_to_the_investigator():
    from faultline.agent.phases import POST_VERDICT, investigation_toolset

    assert POST_VERDICT and not POST_VERDICT & set(investigation_toolset())


def test_brain_time_intents_do_not_capture_other_questions():
    from faultline.brain.ask import _intent

    assert _intent("Who has knowledge of payment?") == "people"            # not a knowledge-health question
    assert _intent("Who is the owner on call for checkout?") == "people"   # "owner on" alone is not the past
    assert _intent("Who was the owner of ad on 2026-06-01?") == "owner_then"
    assert _intent("Who owned fraud-detection during inc-h002?") == "owner_then"
    assert _intent("Where is our knowledge stale?") == "knowledge"
    assert _intent("What is the history of payment?") == "history"


def test_thin_flag_history_defers_to_the_kind_row():
    from faultline.actions.act import _history_row

    by = {("flip_flag", "fx"): {"kind": "flip_flag", "target": "fx", "n": 1, "rate": 0.67},
          ("flip_flag", "*"): {"kind": "flip_flag", "target": "*", "n": 9, "rate": 0.82}}
    o = {"kind": "flip_flag", "target": "fx"}
    assert _history_row(o, by, min_n=2)["target"] == "*"
    assert _history_row(o, by, min_n=1)["target"] == "fx"
