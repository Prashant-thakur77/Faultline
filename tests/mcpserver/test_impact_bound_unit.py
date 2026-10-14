"""impact_bound (G5's bound) without FalkorDB: a fake read-only wrapper returns the template rows, so the tool's own
rules are tested in isolation: it refuses more than 20 suspects, carries every per-source run of the union bound in
its evidence, and reads an incomplete path multiplicity as UNKNOWN (flow_share None), never as a number."""

import pytest

from faultline.graph.ro import QueryResult
from faultline.mcp_server import context
from faultline.mcp_server import tools as T


class _FakeRO:
    def __init__(self, flows: dict, paths: dict, mult_truncated: bool = False):
        self.flows, self.paths, self.mult_truncated, self.calls = flows, paths, mult_truncated, []

    def run(self, tid: str, params: dict) -> QueryResult:
        self.calls.append((tid, params))
        if tid == "Q-GATE-3":
            key = tuple(sorted(params["sources"]))
            rows = [{"max_flow": self.flows[key], "sources": len(key)}] if key in self.flows else []
            return QueryResult(tid, "// q3", params, [], rows, 1.0, f"d{key}")
        if tid == "Q-GATE-MULT":
            rows = [{"source": s, "paths": self.paths.get(s, 1)} for s in params["sources"]]
            return QueryResult(tid, "// mult", params, [], rows, 1.0, "dm", truncated=self.mult_truncated)
        raise AssertionError(tid)


@pytest.fixture
def unbound():
    tok = context.bind("acme", run_id=None, record=False)
    yield
    context.unbind(tok)


def test_more_than_twenty_suspects_is_refused_not_cut(unbound, monkeypatch):
    fake = _FakeRO({}, {})
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.impact_bound(suspect_ids=[f"s{i}" for i in range(21)], symptom_id="checkout", observed_share=0.3)
    assert "error" in out and "at most 20" in out["error"] and not fake.calls


def test_the_union_bound_evidence_carries_every_per_source_run(unbound, monkeypatch):
    fake = _FakeRO({("a", "b"): 0.3, ("a",): 0.1, ("b",): 0.2}, {"a": 2, "b": 1})
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.impact_bound(suspect_ids=["a", "b"], symptom_id="checkout", observed_share=0.5)
    assert out["flow_share"] == pytest.approx(2 * 0.1 + 0.2)
    assert out["template"] == "Q-GATE-3+Q-GATE-MULT+Q-GATE-3+Q-GATE-3"
    assert out["params"]["Q-GATE-3#2"]["sources"] == ["a"] and out["params"]["Q-GATE-3#3"]["sources"] == ["b"]
    assert out["params"]["Q-GATE-3"]["sources"] == ["a", "b"]


def test_a_truncated_multiplicity_is_unknown_not_a_number(unbound, monkeypatch):
    fake = _FakeRO({("a",): 0.1}, {"a": 3}, mult_truncated=True)
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.impact_bound(suspect_ids=["a"], symptom_id="checkout", observed_share=0.9)
    assert out["flow_share"] is None and out["verdict"] == "unknown" and "truncated" in out["unknown_reason"]


def test_a_path_count_at_the_cap_is_unknown_unless_the_bound_is_already_one(unbound, monkeypatch):
    fake = _FakeRO({("a",): 0.001}, {"a": T.MULT_PATH_CAP})
    monkeypatch.setattr(T, "_ro", lambda: fake)
    out = T.impact_bound(suspect_ids=["a"], symptom_id="checkout", observed_share=0.9)
    assert out["flow_share"] is None and out["verdict"] == "unknown"
    fake2 = _FakeRO({("a",): 0.05}, {"a": T.MULT_PATH_CAP})
    monkeypatch.setattr(T, "_ro", lambda: fake2)
    assert T.impact_bound(suspect_ids=["a"], symptom_id="checkout", observed_share=0.9)["flow_share"] == 1.0
