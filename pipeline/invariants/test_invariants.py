"""Invariant tests for the Faultline demo warehouse.

These read data/warehouse/faultline.duckdb (build it first: `make build` or
`make demo-reset` / `make demo-healthy`) plus the committed healthy baselines
in pipeline/baselines/. They encode generic data-quality expectations only —
nothing here knows what (if anything) is wrong with the data.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "warehouse" / "faultline.duckdb"
BASELINES_DIR = REPO_ROOT / "pipeline" / "baselines"

ANCHOR_DAY = date(2026, 8, 9)  # fixed fixture "today" (matches generator)
LAST_7_DAYS = [str(ANCHOR_DAY - timedelta(days=k)) for k in range(6, -1, -1)]

KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "CAD"}
# cloudpay_v2 is a sanctioned provider migration, not an anomaly by itself.
KNOWN_PROCESSORS = {"legacy_pos", "shopgate", "cloudpay_v2"}

IMMUTABLE_THROUGH = "2026-08-04"
SPOT_DAYS = ["2026-05-20", "2026-06-25", "2026-07-30"]


@pytest.fixture(scope="session")
def con():
    assert DB_PATH.exists(), f"warehouse missing at {DB_PATH} — run `make build` first"
    c = duckdb.connect(str(DB_PATH), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="session")
def revenue_baseline():
    path = BASELINES_DIR / "daily_revenue_baseline.json"
    return {row["day"]: row for row in json.loads(path.read_text())}


def _one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()[0]


# ---------------------------------------------------------------------------
# Schema / integrity
# ---------------------------------------------------------------------------
def test_order_id_unique(con):
    dupes = _one(con, "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM staging.stg_orders")
    assert dupes == 0, f"{dupes} duplicate order_ids"


def test_no_null_order_id(con):
    assert _one(con, "SELECT COUNT(*) FROM staging.stg_orders WHERE order_id IS NULL") == 0


def test_no_null_amount(con):
    assert _one(con, "SELECT COUNT(*) FROM staging.stg_orders WHERE amount IS NULL") == 0


def test_no_null_order_ts(con):
    assert _one(con, "SELECT COUNT(*) FROM staging.stg_orders WHERE order_ts IS NULL") == 0


def test_currency_in_known_set(con):
    seen = {r[0] for r in con.execute("SELECT DISTINCT currency FROM staging.stg_orders").fetchall()}
    assert seen <= KNOWN_CURRENCIES, f"unknown currencies: {seen - KNOWN_CURRENCIES}"


def test_processor_in_known_set(con):
    seen = {
        r[0] for r in con.execute("SELECT DISTINCT payment_processor FROM staging.stg_orders").fetchall()
    }
    assert seen <= KNOWN_PROCESSORS, f"unknown processors: {seen - KNOWN_PROCESSORS}"


def test_fct_day_count_matches_order_days(con):
    fct_days = _one(con, "SELECT COUNT(*) FROM marts.fct_revenue")
    order_days = _one(con, "SELECT COUNT(DISTINCT order_day) FROM staging.stg_orders")
    assert fct_days == order_days


# ---------------------------------------------------------------------------
# Conservation
# ---------------------------------------------------------------------------
def test_stg_row_conservation(con):
    stg = _one(con, "SELECT COUNT(*) FROM staging.stg_orders")
    raw = _one(
        con,
        "SELECT COUNT(*) FROM raw.raw_orders WHERE status NOT IN ('cancelled', 'refunded')",
    )
    assert stg == raw, f"stg_orders has {stg} rows, raw non-cancelled/refunded has {raw}"


def test_fct_order_sum_matches_stg(con):
    fct_sum = _one(con, "SELECT SUM(order_count) FROM marts.fct_revenue")
    stg = _one(con, "SELECT COUNT(*) FROM staging.stg_orders")
    assert fct_sum == stg, f"fct order_count sum {fct_sum} != stg row count {stg}"


# ---------------------------------------------------------------------------
# Value sanity
# ---------------------------------------------------------------------------
def test_no_nonpositive_amounts(con):
    assert _one(con, "SELECT COUNT(*) FROM staging.stg_orders WHERE amount <= 0") == 0


def test_max_usd_amount_sane(con):
    max_usd = _one(
        con,
        """
        SELECT MAX(o.amount * fx.usd_rate)
        FROM staging.stg_orders o
        JOIN staging.stg_fx_rates fx
          ON fx.rate_day = o.order_day AND fx.currency = o.currency
        """,
    )
    assert max_usd < 10000, f"max usd order amount {max_usd:.2f} >= 10000"


# ---------------------------------------------------------------------------
# AOV sanity (per day, last 7 days)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("day", LAST_7_DAYS)
def test_aov_median_in_range(con, day):
    aov = _one(con, "SELECT aov_median_usd FROM marts.fct_revenue WHERE day = ?", [day])
    assert aov is not None, f"no fct_revenue row for {day}"
    assert 30.0 <= aov <= 250.0, f"{day}: median AOV {aov:.2f} outside [30, 250] USD"


# ---------------------------------------------------------------------------
# Revenue continuity (per day, last 7 days, vs trailing 14-day median)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("day", LAST_7_DAYS)
def test_revenue_continuity(con, day):
    rev = _one(con, "SELECT revenue_usd FROM marts.fct_revenue WHERE day = ?", [day])
    trailing = _one(
        con,
        """
        SELECT MEDIAN(revenue_usd) FROM marts.fct_revenue
        WHERE day BETWEEN CAST(? AS DATE) - 14 AND CAST(? AS DATE) - 1
        """,
        [day, day],
    )
    assert rev is not None and trailing is not None
    ratio = rev / trailing
    assert 0.35 <= ratio <= 2.8, (
        f"{day}: revenue {rev:.2f} is {ratio:.2f}x trailing 14d median {trailing:.2f}"
    )


# ---------------------------------------------------------------------------
# Historical immutability (vs committed healthy baseline)
# ---------------------------------------------------------------------------
def test_historical_immutability_aggregate(con, revenue_baseline):
    rows = con.execute(
        "SELECT day, revenue_usd FROM marts.fct_revenue WHERE day <= CAST(? AS DATE) ORDER BY day",
        [IMMUTABLE_THROUGH],
    ).fetchall()
    assert len(rows) > 0
    for d, rev in rows:
        base = revenue_baseline[str(d)]["revenue_usd"]
        assert abs(rev - base) <= 0.005 * base, (
            f"{d}: revenue {rev:.2f} deviates >0.5% from baseline {base:.2f}"
        )


@pytest.mark.parametrize("day", SPOT_DAYS)
def test_historical_spot_day(con, revenue_baseline, day):
    rev = _one(con, "SELECT revenue_usd FROM marts.fct_revenue WHERE day = ?", [day])
    base = revenue_baseline[day]["revenue_usd"]
    assert abs(rev - base) <= 0.005 * base, (
        f"{day}: revenue {rev:.2f} deviates >0.5% from baseline {base:.2f}"
    )


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------
def test_fx_rate_coverage(con):
    missing = _one(
        con,
        """
        SELECT COUNT(*)
        FROM staging.stg_orders o
        LEFT JOIN staging.stg_fx_rates fx
          ON fx.rate_day = o.order_day AND fx.currency = o.currency
        WHERE fx.usd_rate IS NULL
        """,
    )
    assert missing == 0, f"{missing} order rows lack an FX rate after forward-fill"


def test_fx_rates_positive(con):
    assert _one(con, "SELECT MIN(usd_rate) FROM staging.stg_fx_rates") > 0


# ---------------------------------------------------------------------------
# Metric consistency
# ---------------------------------------------------------------------------
def test_metric_matches_fct_latest(con):
    kpi_day, revenue = con.execute(
        "SELECT kpi_day, revenue FROM marts.exec_revenue_metric"
    ).fetchone()
    latest_day, latest_rev = con.execute(
        "SELECT day, revenue_usd FROM marts.fct_revenue ORDER BY day DESC LIMIT 1"
    ).fetchone()
    assert kpi_day == latest_day
    assert revenue == latest_rev
