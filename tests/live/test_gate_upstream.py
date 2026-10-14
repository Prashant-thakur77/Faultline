"""Live: G4 upstream (deep bench, PREREGISTRATION 2026-10-14 and its addenda). Elimination uses a STRICT lower bound
(the upstream fault started first, and its excess × the best single path's cap × call share covers the suspect's whole
excess, no slack); a GENEROUS upper bound may only downgrade a confirmed change to not confident. One case per
mechanism, plus the adversarial worlds where the first-shipped rule (upper bound + slack, no onset) blamed the wrong
change with confidence."""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))


@pytest.fixture(scope="module")
def cases(db):
    import deep_bench

    return {c["id"]: c for c in deep_bench.generate(seed=deep_bench.SEED)}


def _run(cases, cid):
    import gate_bench

    c = cases[cid]
    return c, gate_bench.run_case(c)["got"]


def test_strict_elimination_removes_a_lookalike_on_the_alerting_service(cases):
    c, got = _run(cases, "db022")
    assert got["outcome"] == "CONFIRMED" and got["cause"] == c["expected"]["cause"], got
    look = next(x["change"] for x in c["spec"]["inject"] if x["target"] == c["lookalike"])
    assert got["sweep"][look].startswith("eliminated: G4 upstream"), got["sweep"]


def test_strict_elimination_leaves_nothing_to_blame_below_an_unchanged_break(cases):
    c, got = _run(cases, "db041")
    assert got["cause"] is None and all(v.startswith("eliminated: G4 upstream") for v in got["sweep"].values()), got


def test_a_lookalike_the_strict_bound_cannot_eliminate_is_still_not_blamed(cases):
    """db042: the strict bound leaves the look-alike standing; G4 origin, G7 and the upper-bound downgrade all apply
    (in the generated worlds no case needs the downgrade alone: it is defense in depth)."""
    c, got = _run(cases, "db042")
    assert got["cause"] is None and got["outcome"] in ("NOT_CONFIDENT", "UNKNOWN_ESCALATED"), got


@pytest.mark.parametrize("cid", ["db103", "db062", "db081"])   # late upstream fault, two causes, weak (low-share) link
def test_no_wrong_confident_blame_where_the_first_shipped_rule_made_one(cases, cid):
    c, got = _run(cases, cid)
    assert got["cause"] is None or got["cause"] == c["expected"]["cause"], got
