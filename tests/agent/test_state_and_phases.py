"""Stage order (forward-only, terminals sticky, exits from anywhere) and the per-stage / per-role tool whitelists."""

import itertools

import pytest

from faultline.agent import datatools, phases
from faultline.agent.state import EXITS, LEGACY, ORDER, TERMINALS, Stage, can_advance, ordinal
from faultline.mcp_server import tools as T


def test_every_forward_edge_of_the_order_is_allowed_and_every_backward_or_same_edge_is_not():
    non_terminal = [s for s in ORDER if s not in TERMINALS]
    for a, b in itertools.product(non_terminal, ORDER):
        assert can_advance(a, b) == (ORDER.index(b) > ORDER.index(a)), (a, b)


def test_consecutive_stages_chain_from_intake_to_resolved():
    for a, b in zip(ORDER, ORDER[1:]):
        assert can_advance(a, b), (a, b)


@pytest.mark.parametrize("exit_", sorted(EXITS, key=lambda s: s.value))
def test_exits_are_reachable_from_every_non_terminal_stage(exit_):
    for s in Stage:
        if s not in TERMINALS:
            assert can_advance(s, exit_), (s, exit_)


@pytest.mark.parametrize("terminal", sorted(TERMINALS, key=lambda s: s.value))
def test_terminals_are_sticky(terminal):
    # UNKNOWN_ESCALATED included: once escalated, nothing (not even RESOLVED or another exit) moves it
    for target in Stage:
        assert not can_advance(terminal, target), (terminal, target)


def test_exits_sort_after_every_ordered_stage_and_legacy_names_map_forward():
    assert all(ordinal(e) > ordinal(s) for e in EXITS for s in ORDER)
    legacy = list(LEGACY.values())
    assert all(ordinal(a) < ordinal(b) for a, b in zip(legacy, legacy[1:]))


def test_recall_offers_session_history():
    assert "session_history" in phases.PHASE_TOOLS[Stage.RECALL]
    assert "session_history" in phases.llm_toolset(Stage.RECALL)


def test_llm_toolset_is_per_stage_and_never_offers_post_verdict_reads():
    for st in Stage:
        offered = phases.llm_toolset(st)
        assert not phases.POST_VERDICT & set(offered), st
        assert set(offered) <= set(phases.stage_toolset(st)), st
        assert offered[-1] == "finish"
    inv = set(phases.llm_toolset(Stage.INVESTIGATE))
    # earlier stages run as code; their tools are not offered in INVESTIGATE (unless INVESTIGATE lists them itself)
    for t in ("blast_radius", "chokepoints", "similar_incidents", "find_entities", "rank_causes", "who_fixes"):
        assert t not in inv, t
    # the gate is entered from INVESTIGATE (the stage only becomes GATE when the gate accepts)
    assert {"confirm_root_cause", "declare_no_incident"} <= inv
    assert set(phases.llm_toolset(Stage.GATE)) == {"confirm_root_cause", "declare_no_incident", "reachable_from_changes",
                                                   "finish"}
    assert phases.investigation_toolset() == phases.llm_toolset(Stage.INVESTIGATE)


def test_write_tools_exist_only_after_approval():
    before = [s for s in ORDER if ordinal(s) < ordinal(Stage.AWAITING_APPROVAL)]
    for st in before:
        assert not {"execute_action", "write_back"} & set(phases.stage_toolset(st)), st
    assert phases.stage_toolset(Stage.AWAITING_APPROVAL) == ["finish"]


def test_specialist_whitelists_are_subsets_of_investigate_and_name_real_tools():
    inv = set(phases.PHASE_TOOLS[Stage.INVESTIGATE])
    real = set(T.TOOLS) | set(datatools.TOOLS)
    for role in phases.SPECIALIST_TOOLS:
        tools = phases.specialist_toolset(role)
        assert tools and set(tools) <= inv, role
        assert set(tools) <= real, (role, set(tools) - real)
        assert "update_hypothesis" not in tools and "confirm_root_cause" not in tools
    assert phases.specialist_toolset("code") == ["diff_summary"]
    with pytest.raises(KeyError):
        phases.specialist_toolset("oracle")
