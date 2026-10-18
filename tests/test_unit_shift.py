"""Unit (no FalkorDB, no warehouse): the measured data repair's pure parts (agent/unit_shift.py).

* find_shift takes the one segment that is nearly all outside the healthy range, holds nearly all the outside rows,
  whose complement is clean, and whose median is a power of ten off; anything else is None (no guess);
* scoped_fix rewrites exactly one `<expr> AS <column>` line of a transform into a CASE scoped to that segment, and the
  result passes the transform validator; a column the transform does not define that way is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from faultline import repair
from faultline.agent import unit_shift as U

ROOT = Path(__file__).resolve().parents[1]
RULE = {"tolerance": 0.15, "purity": 0.95, "min_rows": 20}


def _seg(**kw):
    base = {"segment": "proc", "value": "v2", "n": 300, "outside": 297, "median": 6400.0, "other_n": 2000,
            "other_outside": 4, "other_median": 62.0, "total_outside": 300, "since_day": "2026-08-07", "existed_before": False}
    return {**base, **kw}


def test_a_scoped_power_of_ten_shift_is_found_with_its_numbers():
    hit = U.find_shift([_seg()], **RULE)
    assert hit and (hit["segment"], hit["value"], hit["power"]) == ("proc", "v2", 2)
    assert hit["purity"] == 0.99 and hit["coverage"] == 0.99 and hit["factor"] == round(6400 / 62, 4)


@pytest.mark.parametrize("bad", [
    {"outside": 200},                      # a third of the segment is healthy: not a shift of the segment
    {"total_outside": 600},                # the segment holds only half the bad rows
    {"other_outside": 400},                # the complement is bad too: this column does not discriminate
    {"median": 2000.0},                    # 32×: not a power of ten
    {"median": 10.0},                      # below the others: never divided up
    {"median": 640000.0, "other_median": 0.062},  # 10^7: outside the powers considered
    {"n": 10, "outside": 10},              # too few rows to call
    {"other_n": 0},                        # nothing to compare with
])
def test_anything_short_of_the_rule_is_none(bad):
    assert U.find_shift([_seg(**bad)], **RULE) is None


def test_the_best_covering_segment_wins_deterministically():
    weak = _seg(segment="currency", value="USD", n=290, outside=287, total_outside=300)
    assert U.find_shift([weak, _seg()], **RULE)["segment"] == "proc"
    assert U.find_shift([_seg(), weak], **RULE)["segment"] == "proc"


def test_a_value_that_appeared_with_the_anomaly_beats_one_that_existed_and_equal_fits_are_no_answer():
    status = _seg(segment="status", value="completed", existed_before=True)   # every row that day is completed too
    assert U.find_shift([status, _seg()], **RULE)["segment"] == "proc"
    assert U.find_shift([status, _seg(existed_before=True)], **RULE) is None   # indistinguishable: nothing proposed
    old = _seg(existed_before=True, since_day="2026-08-07")
    hit = U.find_shift([old], **RULE)
    text = U.explain(hit, "t", "amount", "f.sql", ["ev"])
    assert "from 2026-08-07" in text


STG = (ROOT / "pipeline" / "transforms_pristine" / "stg_orders.sql").read_text()


def test_scoped_fix_wraps_exactly_the_column_and_passes_the_validator():
    out = U.scoped_fix(STG, "amount", "payment_processor", "cloud-pay.v2", 2)
    assert out and out.count("CASE WHEN") == 1
    assert "    CASE WHEN payment_processor = 'cloud-pay.v2' THEN (CAST(amount AS DOUBLE)) / 100 ELSE CAST(amount AS DOUBLE) END AS amount,\n" in out
    assert out.replace("CASE WHEN payment_processor = 'cloud-pay.v2' THEN (CAST(amount AS DOUBLE)) / 100 ELSE CAST(amount AS DOUBLE) END AS amount,",
                       "CAST(amount AS DOUBLE) AS amount,") == STG                     # nothing else moved
    repair.validate_transform_sql("pipeline/transforms/stg_orders.sql", out)             # the existing allowlist holds
    dated = U.scoped_fix(STG, "amount", "payment_processor", "v2", 2, since_day="2026-08-07", ts_expr="order_ts")
    assert dated and "AND CAST(order_ts AS TIMESTAMP) >= TIMESTAMP '2026-08-07 00:00:00' THEN" in dated
    repair.validate_transform_sql("pipeline/transforms/stg_orders.sql", dated)


@pytest.mark.parametrize("args", [
    ("revenue", "payment_processor", "v2", 2),        # not an output column of this transform
    ("amount", "payment processor", "v2", 2),          # not an identifier
    ("amount", "payment_processor", "v2;--", 2),       # not a plain value
    ("amount", "payment_processor", "cloud'pay", 2),   # a quote is never written into SQL
    ("amount", "payment_processor", "v2", 9),          # not a power the rule allows
])
def test_scoped_fix_refuses_rather_than_guesses(args):
    assert U.scoped_fix(STG, *args) is None


def test_scoped_fix_never_wraps_twice_and_needs_one_definition():
    once = U.scoped_fix(STG, "amount", "payment_processor", "v2", 2)
    assert U.scoped_fix(once, "amount", "payment_processor", "v2", 2) is None
    twice = STG.replace("    status\n", "    status,\n    amount AS amount\n")
    assert U.scoped_fix(twice, "amount", "payment_processor", "v2", 2) is None


def test_explain_names_the_numbers_and_the_evidence():
    hit = U.find_shift([_seg()], **RULE)
    text = U.explain(hit, "staging.stg_orders", "amount", "pipeline/transforms/stg_orders.sql", ["ev_a", "ev_b"])
    assert "proc = 'v2'" in text and "10^2" in text and "divides only those rows by 100" in text and "ev_a, ev_b" in text


def test_the_date_clause_needs_a_time_column_the_transform_can_see():
    renamed = STG.replace("CAST(order_ts AS TIMESTAMP) AS order_ts", "CAST(placed AS TIMESTAMP) AS order_ts").replace(
        "CAST(CAST(order_ts AS TIMESTAMP) AS DATE) AS order_day", "CAST(CAST(placed AS TIMESTAMP) AS DATE) AS order_day")
    assert "order_ts" in renamed and " placed " not in renamed
    out = U.scoped_fix(renamed, "amount", "payment_processor", "v2", 2, since_day="2026-08-07", ts_expr="placed_at")
    assert out and "TIMESTAMP '" not in out                           # segment-only: the column is not visible
    hit = U.find_shift([_seg(existed_before=True, since_day="2026-08-07")], **RULE)
    text = U.explain(hit, "t", "amount", "f.sql", ["ev"], dated=False)
    assert "healthy before 2026-08-07" in text and "every row of the segment is divided" in text
    assert "from 2026-08-07" in U.explain(hit, "t", "amount", "f.sql", ["ev"], dated=True)


def test_commit_subjects_cut_at_a_word():
    from faultline.actions.act import _subject

    assert _subject("short") == "short"
    long = "unit shift measured on staging.stg_orders.amount: the 327 rows with payment_processor = 'cloudpay_v2' are"
    s = _subject(long)
    assert len(s) <= 61 and s.endswith("…") and not s[:-1].endswith(" ") and s[:-1] in long and long[len(s) - 1] == " "
