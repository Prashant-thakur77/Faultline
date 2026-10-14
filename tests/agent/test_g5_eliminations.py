"""The joint G5 elimination (agent/gate.py::g5_eliminations / g5_jointly_sufficient): a suspect goes only when another
suspect can carry the impact ALONE; suspects that only a group can explain are all unresolved, never one of them
eliminated on the strength of the others (that choice would depend on the order)."""

import itertools

from faultline.agent.gate import g5_cross_group, g5_eliminations, g5_jointly_sufficient


def _joint(caps):
    return lambda targets: min(1.0, sum(caps[t] for t in targets))


def test_three_suspects_that_only_pairs_can_explain_are_all_unresolved_none_eliminated():
    """Review: need 0.5; A, B, C each 0.3; any pair ≥ 0.6. Eliminating one of them (the old one-at-a-time pass took
    the lowest id) rests on the others, which are just as insufficient alone: none goes, all three are unresolved."""
    caps = {"a": 0.3, "b": 0.3, "c": 0.3}
    cands, bounds = {"A": "a", "B": "b", "C": "c"}, {"A": 0.3, "B": 0.3, "C": 0.3}
    assert g5_eliminations(cands, bounds, 0.5, _joint(caps)) == []
    assert g5_jointly_sufficient(cands, bounds, 0.5, _joint(caps)) == ["A", "B", "C"]


def test_decoy_eliminated_while_the_sufficient_cause_stays():
    caps = {"pay": 1.0, "email": 0.02}
    cands, bounds = {"D-pay": "pay", "D-email": "email"}, {"D-pay": 1.0, "D-email": 0.02}
    out = g5_eliminations(cands, bounds, 0.24, _joint(caps))
    assert [c for c, _, _ in out] == ["D-email"] and out[0][2] == 1.0
    assert g5_jointly_sufficient({"D-pay": "pay"}, bounds, 0.24, _joint(caps)) == []   # sufficient alone: not multi-cause


def test_unknown_bound_is_never_eliminated_and_no_one_goes_on_an_unknown():
    caps = {"x": 0.1, "y": 0.9}
    out = g5_eliminations({"X": "x", "Y": "y"}, {"X": None, "Y": 0.1}, 0.5, _joint(caps))
    assert out == [] or all(c != "X" for c, _, _ in out)
    assert ("Y", 0.1, 0.1) not in out                    # X alone (plain flow 0.1) cannot carry 0.5


def test_the_result_does_not_depend_on_the_order_the_suspects_come_in():
    caps = {"a": 0.2, "b": 0.2, "c": 0.35, "s": 0.9}
    bounds = {"A": 0.2, "B": 0.2, "C": 0.35, "S": 0.9}
    seen = set()
    for perm in itertools.permutations(["A", "B", "C", "S"]):
        cands = {k: k.lower() for k in perm}
        seen.add(tuple(g5_eliminations(cands, bounds, 0.5, _joint(caps))))
    assert seen == {(("A", 0.2, 0.9), ("B", 0.2, 0.9), ("C", 0.35, 0.9))}   # S alone carries it: the rest go, always


def test_an_elimination_never_rests_on_a_group():
    """A and B together can carry 0.5, neither alone: C (0.1) is not eliminated on their strength either; all stand
    for the multi-cause verdict."""
    caps = {"a": 0.3, "b": 0.3, "c": 0.1}
    cands, bounds = {"A": "a", "B": "b", "C": "c"}, {"A": 0.3, "B": 0.3, "C": 0.1}
    assert g5_eliminations(cands, bounds, 0.5, _joint(caps)) == []
    assert g5_jointly_sufficient(cands, bounds, 0.5, _joint(caps)) == ["A", "B", "C"]


def test_a_multi_target_change_is_judged_on_all_its_targets():
    """A change that touched two components: its plain flow is the joint flow of both, so it can carry what either
    alone cannot, and it eliminates a decoy that a single-target reading would have kept."""
    caps = {"p": 0.3, "q": 0.3, "e": 0.02}
    cands, bounds = {"D-multi": ["p", "q"], "D-decoy": "e"}, {"D-multi": 0.6, "D-decoy": 0.02}
    assert [c for c, _, _ in g5_eliminations(cands, bounds, 0.5, _joint(caps))] == ["D-decoy"]


# ------------------------------------------------------------------ across symptom groups (review round 4, m2)
def _group_elims(groups, cands, caps_by_group, need_by_group):
    """Each group judged against the SAME candidate set, as Gate.sweep now does."""
    out = {}
    for sym in groups:
        caps = caps_by_group[sym]
        bounds = {c: caps[t] for c, t in cands.items()}
        out[sym] = {c for c, _, _ in g5_eliminations(cands, bounds, need_by_group[sym], _joint(caps))}
    return out


def test_a_suspect_that_explains_one_group_is_not_dropped_for_failing_another():
    """X carries group B alone (and nothing else does) but not group A, where Y carries it: X is eliminated in A only.
    The old sequential pass dropped X while looking at A, leaving B with no suspect; now X stays."""
    cands = {"X": "x", "Y": "y"}
    caps = {"A": {"x": 0.05, "y": 0.9}, "B": {"x": 0.9, "y": 0.0}}
    reach = {"X": {"A", "B"}, "Y": {"A"}}
    elim = _group_elims(["A", "B"], cands, caps, {"A": 0.5, "B": 0.5})
    assert elim == {"A": {"X"}, "B": {"Y"}}
    assert g5_cross_group(reach, elim) == []          # X explains B; Y reaches only A and is sufficient there


def test_eliminated_in_every_group_it_reaches_goes():
    cands = {"D": "d", "P": "p", "Q": "q"}
    caps = {"A": {"d": 0.01, "p": 0.9, "q": 0.0}, "B": {"d": 0.01, "p": 0.0, "q": 0.9}}
    reach = {"D": {"A", "B"}, "P": {"A"}, "Q": {"B"}}
    elim = _group_elims(["A", "B"], cands, caps, {"A": 0.4, "B": 0.4})
    assert g5_cross_group(reach, elim) == ["D"]


def test_an_unmeasured_group_protects_the_suspects_that_reach_it():
    reach = {"D": {"A", "B"}}
    assert g5_cross_group(reach, {"A": {"D"}}) == []          # B unmeasured: no elimination by flow there
    assert g5_cross_group(reach, {"A": {"D"}, "B": {"D"}}) == ["D"]
    assert g5_cross_group({"E": set()}, {"A": {"E"}}) == []    # no path to any group: G2's business, not G5's


def test_cross_group_result_does_not_depend_on_group_order():
    cands = {"X": "x", "Y": "y", "Z": "z"}
    caps = {"A": {"x": 0.05, "y": 0.9, "z": 0.1}, "B": {"x": 0.9, "y": 0.0, "z": 0.1}, "C": {"x": 0.2, "y": 0.2, "z": 0.8}}
    reach = {"X": {"A", "B", "C"}, "Y": {"A", "C"}, "Z": {"A", "B", "C"}}
    need = {"A": 0.5, "B": 0.5, "C": 0.5}
    seen = set()
    for order in itertools.permutations(["A", "B", "C"]):
        elim = _group_elims(list(order), cands, caps, need)
        seen.add(tuple(g5_cross_group(reach, elim)))
    assert seen == {()}  # each suspect explains some group it reaches: none is eliminated, whatever the order
