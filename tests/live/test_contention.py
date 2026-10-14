"""Live (reduced, for judge-check): 8 responders, each its own client, approve at once; exactly one approval lands,
with one intent and one Operator step; then 8 responders race on different options with the same outcome. Full run:
evals/contention.py (24 responders)."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def test_one_approval_lands_under_contention():
    spec = importlib.util.spec_from_file_location("contention", ROOT / "evals" / "contention.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.run(n=8)
    same, diff = res["same_plan"], res["different_plans"]
    assert (same["accepted"], same["refused"], same["approved_actions"], same["intents"], same["operator_steps"], same["prs"]) \
        == (1, 7, 1, 1, 1, 1), same
    assert diff["accepted"] == 1 and diff["approved_actions"] == 1 and diff["intents"] <= 1 and diff["operator_steps"] == 1, diff
