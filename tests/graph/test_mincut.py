import pytest

from faultline.graph.algo.maxflow import CutMismatch, min_cut

EDGES = [("s", "a", "sa"), ("s", "b", "sb"), ("a", "c", "ac"), ("b", "c", "bc"), ("c", "t", "ct")]
CAP = {"sa": 10, "sb": 10, "ac": 1, "bc": 2, "ct": 10}


def test_fixture_cut_from_engine_style_flows():
    # edgeFlows as returned by algo.maxFlow (positive-flow edges only; others default to 0)
    flow = {"sa": 1, "sb": 2, "ac": 1, "bc": 2, "ct": 3}
    cut, side = min_cut({"s"}, EDGES, CAP, flow, 3.0)
    assert sorted(e[2] for e in cut) == ["ac", "bc"]
    assert side == {"s", "a", "b"}


def test_zero_flow_edges_must_be_included_for_residual_reachability():
    edges = EDGES + [("s", "d", "sd"), ("d", "t", "dt")]
    cap = {**CAP, "sd": 5, "dt": 0.0}
    flow = {"sa": 1, "sb": 2, "ac": 1, "bc": 2, "ct": 3}
    cut, _ = min_cut({"s"}, edges, cap, flow, 3.0)
    assert sorted(e[2] for e in cut) == ["ac", "bc"]


def test_misaligned_flows_fail_loudly():
    with pytest.raises(CutMismatch):
        min_cut({"s"}, EDGES, CAP, {"sa": 1, "sb": 2, "ac": 1, "bc": 2, "ct": 3}, 4.0)


def test_targets_on_source_side_fail_loudly():
    flow = {"sa": 1, "sb": 2, "ac": 1, "bc": 2, "ct": 3}
    with pytest.raises(CutMismatch):
        min_cut({"s"}, EDGES, CAP, flow, 3.0, targets={"a"})
    cut, _ = min_cut({"s"}, EDGES, CAP, flow, 3.0, targets={"t"})
    assert len(cut) == 2


def test_zero_flow_means_no_cut():
    assert min_cut({"s"}, EDGES, CAP, {}, 0.0, targets={"t"}) == ([], {"s"})
