"""Unit: the M18 numbers audit's grading and interval code (evals/report.py, evals/harness.py, evals/baselines.py)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import report  # noqa: E402


def test_wilson_matches_known_values():
    assert report.wilson(0, 140) == (0.0, 0.0267)
    assert report.wilson(51, 100) == (0.4135, 0.6058)
    assert report.wilson(8, 8) == (0.6756, 1.0)
    assert report.wilson(0, 0) is None


def test_wilson_keys_shape():
    k = report.wilson_keys("x.y", 4, 8)
    assert k == {"x.y.k": 4, "x.y.n": 8, "x.y.ci_lo": 0.2152, "x.y.ci_hi": 0.7848}


def test_a_tie_is_never_a_correct_verdict():
    """Arm T on S2: both changes measure 0.0; the trial field credited the alphabetically first (the cause)."""
    tr = {"outcome": "CONFIRMED", "cause": "D-cutover-1"}
    tied = {"outcome": "CONFIRMED", "cause": "D-cutover-1", "tied": ["D-cutover-1", "D-fx-pause-7"], "outcome_correct": True}
    assert report._strict(tied, tr) == {"oc": False, "wrong": True}
    single = {"outcome": "CONFIRMED", "cause": "D-cutover-1", "tied": ["D-cutover-1"], "outcome_correct": True}
    assert report._strict(single, tr) == {"oc": True, "wrong": False}


def test_any_blame_on_a_control_is_a_wrong_blame():
    tr = {"outcome": "NO_INCIDENT", "cause": None}
    assert report._strict({"outcome": "CONFIRMED", "cause": "D-ad-5", "tied": ["D-ad-5"], "outcome_correct": False}, tr)["wrong"]
    assert not report._strict({"outcome": "NO_INCIDENT", "cause": None, "outcome_correct": True}, tr)["wrong"]


def test_claim_tag_safe_arm_keys():
    assert report._key_arm("T+") == "Tplus" and report._key_arm("A3-noG5") == "A3-noG5"


def test_telemetry_plus_decision(monkeypatch):
    import harness

    monkeypatch.setattr("faultline.agent.weights.weights", lambda: {"gate": {"err_abs_min": 0.01}})
    d = harness.telemetry_plus_decision
    assert d([0.001], {"D-a": 0.3})["outcome"] == "NO_INCIDENT"           # nothing alerting is anomalous
    assert d([0.3], {"D-a": 0.002, "D-b": None})["outcome"] == "NOT_CONFIDENT"  # no changed component is
    assert d([0.3], {"D-a": 0.2, "D-b": 0.4}) == {"outcome": "CONFIRMED", "tied": ["D-b"]}
    assert d([0.3], {"D-a": 0.4, "D-b": 0.4})["tied"] == ["D-a", "D-b"]


def test_baseline_scores():
    import baselines

    conf = {"outcome": "CONFIRMED", "cause": "D-c"}
    assert baselines.score(conf, {"tied": ["D-c"]})["right_strict"]
    tie = baselines.score(conf, {"tied": ["D-c", "D-x"]})
    assert not tie["right_strict"] and tie["right_frac"] == 0.5 and tie["wrong_frac"] == 0.5
    abst = {"outcome": "NOT_CONFIDENT", "cause": None}
    assert baselines.score(abst, {"tied": []})["right_strict"]
    assert baselines.score(abst, {"tied": ["D-x"]})["wrong_frac"] == 1.0


def test_generators_fix_their_expected_verdicts_before_running():
    import decisive_bench
    import world_bench

    d = decisive_bench.generate()
    assert len(d) == 40 and all(c["expected"]["outcome"] == "CONFIRMED" and c["lookalike"] != c["origin"] for c in d)
    w = world_bench.generate()
    assert len(w) == 100
    for c in w:
        exp = c["expected"]["outcome"]
        assert exp == {"cause": "CONFIRMED", "unchanged": "NOT_CONFIDENT", "quiet": "NO_INCIDENT"}[c["category"]]
        assert (c["expected"]["cause"] is None) == (c["category"] != "cause")
