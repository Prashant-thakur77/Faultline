"""Q-PROTECT-1 at scale (agent/loop.py::protect_entries): more entries than one read returns is a ranked, stated cap,
not an error; only a cap that would drop a tier-1 entry fails loudly."""

import pytest

from faultline.agent.loop import protect_entries
from faultline.graph.ro import QueryResult


def _res(rows, truncated=False):
    return QueryResult("Q-PROTECT-1", "// q", {}, [], rows, 1.0, "d", truncated=truncated)


def _rows(n_tier1, n_other, total=None):
    rows = [{"id": f"t1-{i:02d}", "tier": 1} for i in range(n_tier1)] + [{"id": f"t2-{i:02d}", "tier": 2} for i in range(n_other)]
    t = total if total is not None else len(rows)
    return [{**r, "total": t, "tier1": n_tier1, "kind": "entry"} for r in rows]


def test_all_reachable_entries_fit():
    ids, note = protect_entries(_res(_rows(1, 2)), "payment")
    assert ids == ["t1-00", "t2-00", "t2-01"] and note is None


def test_more_entries_than_one_read_is_a_ranked_cap_that_is_said():
    ids, note = protect_entries(_res(_rows(3, 17, total=26), truncated=True), "hub")
    assert len(ids) == 20 and ids[:3] == ["t1-00", "t1-01", "t1-02"]
    assert "26 entry services" in note and "6 more" in note and "Q-PROTECT-1" in note


def test_a_cap_that_would_drop_a_tier1_entry_fails_loudly():
    rows = [{**r, "tier1": 25} for r in _rows(20, 0, total=30)]
    with pytest.raises(RuntimeError, match="tier-1"):
        protect_entries(_res(rows, truncated=True), "hub")


def test_nothing_reachable():
    assert protect_entries(_res([]), "leaf") == ([], None)
