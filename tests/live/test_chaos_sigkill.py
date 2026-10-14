"""Live: kill -9 the API between EXECUTE and VERIFY; the RESTARTED API's own reconciler (periodic, boot-epoch leases,
real clock: nothing is moved by hand) settles the intent exactly once (one PR, verified APPLIED, write-back n/n,
RESOLVED), and a naive retry without the idempotency key would have merged the change twice. The mechanics live in
evals/chaos.py (also a harness check); this test is the pass/fail."""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))


def test_sigkill_between_execute_and_verify_settles_exactly_once(db):
    import chaos

    r = chaos.run()
    assert r["killed_exit"] == -9
    assert r["after_kill"] == {"stage": "EXECUTE", "intent": "PENDING", "prs": 1, "merged": ["merged"]}
    # settled by the restarted API itself, on the real clock, within its periodic window (review round 5, M1)
    assert r["reconciled"] == [{"found": "at_main", "verdict": "APPLIED", "writeback": r["final"]["writeback"]}]
    assert r["final_stage_seen"] == "RESOLVED" and r["settled_by_restarted_api_s"] > 0
    n, m = r["final"]["writeback"].split("/")
    assert n == m
    assert r["final"]["prs"] == 1 and r["final"]["prs_merged"] == 1
    assert r["final"]["intent"] == "COMMITTED" and r["final"]["stage"] == "RESOLVED"
    assert r["second_reconcile_settled"] == 0 and r["re_execute_refused"]
    assert r["exactly_once"]
    # control: without the idempotency key the same approved change is merged twice
    assert r["control_naive_retry"]["merged_prs"] == 2 and r["double_action_in_control"]
    assert r["ok"]


def test_sigkill_between_github_merge_and_graph_record_settles_exactly_once(db):
    """The crash window between the merge at GitHub and the graph's record of it: the graph does not know the change
    happened, so only the idempotency key (branch / PR lookup) stops a second merge. The reconciler finds the merged PR
    and settles the intent once."""
    import chaos

    r = chaos.run(pause="after_merge_before_record")
    assert r["killed_exit"] == -9
    assert r["after_kill"] == {"stage": "EXECUTE", "intent": "PENDING", "prs": 1, "merged": ["merged"]}
    assert r["recorded_before_kill"] is False                       # the graph had no execution record at the kill
    assert r["reconciled"] and r["reconciled"][0]["verdict"] == "APPLIED"
    assert r["final"]["prs"] == 1 and r["final"]["prs_merged"] == 1
    assert r["final"]["intent"] == "COMMITTED" and r["final"]["stage"] == "RESOLVED"
    assert r["second_reconcile_settled"] == 0 and r["re_execute_refused"] and r["exactly_once"] and r["ok"]


def test_chaos_hooks_refuse_public_mode_and_real_github(monkeypatch, tmp_path):
    from faultline.actions import act
    from faultline.actions import github as gh
    from faultline.config import settings

    marker = tmp_path / "paused"
    monkeypatch.setenv("FAULTLINE_CHAOS_PAUSE", "after_execute")
    monkeypatch.setenv("FAULTLINE_CHAOS_MARKER", str(marker))
    monkeypatch.setenv("FAULTLINE_CHAOS_SLEEP_S", "0")
    monkeypatch.setattr(settings, "faultline_public", True)
    act._chaos_pause("after_execute")
    assert not marker.exists()                                     # public: refused, no pause
    monkeypatch.setattr(settings, "faultline_public", False)
    monkeypatch.setenv("FAULTLINE_GITHUB", "real")
    assert act.chaos_allowed() is False
    act._chaos_pause("after_execute")
    assert not marker.exists()                                     # real GitHub: refused
    monkeypatch.setenv("FAULTLINE_GITHUB", "sim")
    act._chaos_pause("after_execute")
    assert marker.read_text() == "after_execute"                   # the test setup itself still works
    # the persisted simulated GitHub (the other chaos hook) is ignored on the public demo
    monkeypatch.setenv("FAULTLINE_SIM_GITHUB_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "faultline_public", True)
    gh.reset_sim("chaos-hook-probe")
    try:
        assert type(gh.client("chaos-hook-probe")) is gh.SimGitHub
    finally:
        gh.reset_sim("chaos-hook-probe")
