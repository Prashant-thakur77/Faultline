"""The reconciler settles only intents acted in a world it can see: an intent recorded in another process's persisted
simulated GitHub (`dir:<path>`) is left for a reconciler that shares it, instead of being escalated as a reset world.
An in-memory world (`mem`) dies with its process, so any reconciler may still escalate that one (never as success)."""

import types

from faultline.actions import reconcile as R


def _run(monkeypatch, world_of_intent: str, here: str) -> list[str]:
    claimed: list[str] = []
    row = {"incident": "inc-1", "run": "run-1", "idem": "idem-1", "kind": "flip_flag", "world": world_of_intent}
    monkeypatch.setattr(R.boot, "beat", lambda *a, **k: None)
    monkeypatch.setattr(R.boot, "live", lambda *a, **k: [])
    monkeypatch.setattr(R, "RO", lambda t, g: types.SimpleNamespace(run=lambda tid, p: types.SimpleNamespace(rows=[row])))
    monkeypatch.setattr(R.gh, "world_id", lambda: here)
    monkeypatch.setattr(R.act, "Ctx", lambda *a, **k: types.SimpleNamespace(g=lambda: None))
    monkeypatch.setattr(R.writes, "claim_intent", lambda g, **k: claimed.append(k["idem"]) or False)
    R.reconcile("acme", "eval_acme_x", hub=None, world=lambda i: None, older_than_ms=0)
    return claimed


def test_an_intent_in_another_persisted_world_is_left_alone(monkeypatch):
    assert _run(monkeypatch, "dir:/tmp/other-world", "mem") == []
    assert _run(monkeypatch, "dir:/tmp/other-world", "dir:/tmp/mine") == []


def test_same_world_or_in_memory_or_unrecorded_is_reconciled(monkeypatch):
    assert _run(monkeypatch, "dir:/tmp/w", "dir:/tmp/w") == ["idem-1"]
    assert _run(monkeypatch, "mem", "dir:/tmp/w") == ["idem-1"]
    assert _run(monkeypatch, "", "mem") == ["idem-1"]   # intents from before the world was recorded
