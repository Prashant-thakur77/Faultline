"""Unit tests (no FalkorDB) for the backtest's arithmetic (evals/backtest.py) and its RESULTS.md section."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _mod(name, where="evals"):
    spec = importlib.util.spec_from_file_location(name, ROOT / where / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


bt = _mod("backtest")


def _row(causing, verdict, risk, at=0):
    return {"causing": causing, "merged_at": at, "verdict": {"full": verdict}, "risk": {"full": risk}}


def test_auroc_orders_and_ties():
    assert bt.auroc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert bt.auroc([0.1], [0.9]) == 0.0
    assert bt.auroc([0.5, 0.5], [0.5]) == 0.5
    assert bt.auroc([0.6, 0.4], [0.5]) == 0.5
    assert bt.auroc([], [0.1]) is None and bt.auroc([0.1], []) is None


def test_metrics_rates_and_confusion():
    rows = [_row(True, "block", 0.9), _row(True, "require_review", 0.5), _row(True, "allow", 0.1),
            _row(False, "require_review", 0.4), _row(False, "allow", 0.2), _row(False, "allow", 0.2),
            _row(False, "block", 0.7), _row(False, "allow", None)]  # unscorable keeps its verdict, leaves AUROC
    m = bt.metrics(rows, "full")
    assert (m["prs"], m["causing"]) == (8, 3)
    assert m["catch_rate"] == round(2 / 3, 4) and m["block_catch_rate"] == round(1 / 3, 4)
    assert m["block_rate"] == 0.25 and m["review_rate"] == 0.25 and m["flag_rate"] == 0.5
    assert m["false_flag_rate"] == 0.4 and m["precision"] == 0.5
    assert m["confusion"] == {"causing": {"block": 1, "require_review": 1, "allow": 1},
                              "other": {"block": 1, "require_review": 1, "allow": 3}}
    assert m["auroc"] == bt.auroc([0.9, 0.5, 0.1], [0.4, 0.2, 0.2, 0.7])


def test_metrics_with_no_causing_prs_is_none_not_zero():
    m = bt.metrics([_row(False, "allow", 0.1)], "full")
    assert m["catch_rate"] is None and m["auroc"] is None and m["precision"] is None


def test_segments_split_the_window_in_thirds():
    rows = [_row(False, "allow", 0.1, at=t) for t in (0, 10, 32, 33, 66, 67, 99)]
    seg = bt.segment(rows, 0, 99)
    assert [r["merged_at"] for r in seg["first_third"]] == [0, 10, 32]
    assert [r["merged_at"] for r in seg["last_third"]] == [66, 67, 99]
    assert seg["all"] is rows


def test_report_section_tags_every_number_from_the_summary():
    report, claims = _mod("report"), _mod("check_claims", "scripts")
    m = bt.metrics([_row(True, "require_review", 0.5), _row(False, "allow", 0.2)], "full")
    one = {"tenant": "t", "graph": "golden_t", "prs": 2, "causing_prs": 1, "window_ms": [0, 1],
           "variants": {v: {s: m for s in ("all", "first_third", "last_third")} for v in ("full", "no_past_incidents", "leaky_now")},
           "diagnostics": {"unscorable": 0, "impact_truncated": 0, "prs_with_change_facts": 0, "decision_term_nonzero": 0,
                           "self_leaks": 0, "causing_with_prior_incidents": 1}}
    md, summ = "\n".join(report.backtest_markdown({"t": one})), report.backtest_summary({"t": one})
    tags = list(claims.TAG.finditer(md))
    assert len(tags) > 50
    for t in tags:
        assert t.group(1) in summ and claims._eq(t.group(2), summ[t.group(1)]), t.group(0)
    assert "Honest limits" in md and report.backtest_markdown({}) == []


@pytest.mark.parametrize("bad", ["latest.json"])
def test_cli_refuses_to_write_latest_json(bad, monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "run_all", lambda tenants: {})
    monkeypatch.setattr(sys, "argv", ["backtest", "--json", str(tmp_path / bad)])
    with pytest.raises(SystemExit):
        bt.main()
