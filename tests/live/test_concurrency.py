"""Live S13 (reduced for judge-check): 16 workers × 10 rounds race for one task per round; exactly one owner per
round, zero lost updates; handoffs only by the current owner. Full run: evals/concurrency.py (16 × 100)."""

import importlib.util
from pathlib import Path

import pytest

from faultline.graph import client, writes
from faultline.graph import copy as gcopy

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def test_s13_reduced():
    spec = importlib.util.spec_from_file_location("concurrency", ROOT / "evals" / "concurrency.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.run("acme", workers=16, rounds=10, readers=2)
    assert res["passed"], res
    assert res["rounds_with_exactly_one_owner"] == 10 and res["lost_updates"] == 0


def test_handoff_only_by_owner_and_turns_numbered():
    db = client.engine()
    name = "eval_acme_coord_probe"
    gcopy.delete_if_exists(db, name)
    gcopy.copy_graph(db, "golden_acme", name)
    try:
        g = db.select_graph(name)
        assert writes.claim_task(g, task="t1", agent="a1")
        assert not writes.claim_task(g, task="t1", agent="a2")
        assert not writes.hand_off(g, task="t1", from_agent="a2", to_agent="a3")  # not the owner
        assert writes.hand_off(g, task="t1", from_agent="a1", to_agent="a3")
        assert not writes.complete_task(g, task="t1", agent="a1") and writes.complete_task(g, task="t1", agent="a3")
        assert [writes.append_turn(g, session="sess-1", user="u1", role=r, text=r)["seq"] for r in ("user", "assistant")] == [1, 2]
        with pytest.raises(writes.SessionError):  # another user's session
            writes.append_turn(g, session="sess-1", user="intruder", role="user", text="x")
        with pytest.raises(writes.SessionError):  # not server-issued: could take a component's id
            writes.append_turn(g, session="checkout", user="u1", role="user", text="x")
    finally:
        gcopy.delete_if_exists(db, name)
