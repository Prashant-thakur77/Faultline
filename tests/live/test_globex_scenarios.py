"""Live S8 and S11 on the globex tenant (graph-level checks shared with evals/globex_checks.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
import globex_checks  # noqa: E402

pytestmark = pytest.mark.live


def test_s8_recurring_family_recalls_the_family_and_derived_runbook_first():
    r = globex_checks.s8()
    assert r["precedents"] >= 2 and r["precedents_in_family"] == r["precedents"], r
    assert r["first_runbook_derived"] and r["first_runbook_support"] >= 2, r


def test_s11_owner_gone_bus_factor_warning_and_an_active_person_is_paged():
    r = globex_checks.s11()
    assert r["top_contributor_inactive"] and r["bus_factor"] <= 1, r
    assert r["paged_first_active"] and r["escalation_edges"] >= 1, r
