"""M17: G8 is attach-only (never rejects, never downgrades), and the reversal guard is decided in code from Q-DEC-REV rows."""

from faultline.agent.gate import Check, decide
from faultline.agent.rules import reversals


def _base():
    return [Check("G2 path", True, ""), Check("G5 sufficiency", True, ""), Check("G7 correlation", True, "", downgrade_only=True)]


def test_attach_only_never_rejects_or_downgrades():
    with_g8 = _base() + [Check("G8 contradiction", False, "violates ADR-x", downgrade_only=True, attach_only=True)]
    renamed = _base() + [Check("G8 reversal", False, "reinstates ADR-y", downgrade_only=True, attach_only=True)]
    hard_attach = _base() + [Check("anything", False, "", attach_only=True)]
    assert decide(_base()) == decide(with_g8) == decide(renamed) == decide(hard_attach) == (True, True)


def test_a_real_downgrade_still_downgrades():
    assert decide(_base()[:2] + [Check("G7 correlation", False, "", downgrade_only=True)]) == (True, False)


ROW = {"reversed": "ADR-old", "reversed_title": "off-peak", "rule_key": "c.db.window", "op": "==", "old_value": "off_peak",
       "actual": "off_peak", "actual_text": "off_peak", "about": "c", "head": "ADR-new", "head_title": "online",
       "head_decided_at": 2, "head_url": "u", "because": [{"id": "doc", "title": "locks"}]}


def test_reinstating_the_reversed_value_is_flagged_with_what_replaced_it_and_why():
    (r,) = reversals([ROW])
    assert r["reversed"] == "ADR-old" and r["head"] == "ADR-new" and r["because"][0]["title"] == "locks"


def test_a_value_the_old_rule_rejects_is_not_a_reinstatement():
    assert reversals([{**ROW, "actual": "peak", "actual_text": "peak"}]) == []
    assert reversals([{**ROW, "op": "<=", "old_value": 10, "actual": "x"}]) == []   # undecidable: not claimed


def test_text_equality_rules_are_decidable_ordering_on_text_is_not():
    from faultline.agent.rules import violated

    assert violated("==", "online", "online") is False and violated("==", "Off_Peak ", "off_peak") is False
    assert violated("==", "off_peak", "online") is True and violated("!=", "a", "a") is True
    assert violated("<=", "fast", "slow") is None
