"""Regenerate committed baselines from a HEALTHY fixture run.

Runs healthy generation + the full build into a TEMP directory (never touching
data/sources or data/warehouse), profiles the result, and writes:

  pipeline/baselines/daily_revenue_baseline.json
  pipeline/baselines/profile_baseline.json

These files represent the metrics platform's historical observability record
and are committed to git.
"""

import json
import tempfile
from pathlib import Path

import duckdb

import generate_sources
import run as builder

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"


def _daily_revenue_baseline(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute(
        "SELECT day, revenue_usd, order_count, aov_median_usd FROM marts.fct_revenue ORDER BY day"
    ).fetchall()
    return [
        {
            "day": str(d),
            "revenue_usd": float(rev),
            "order_count": int(cnt),
            "aov_median_usd": float(aov),
        }
        for d, rev, cnt, aov in rows
    ]


def _profile_baseline(con: duckdb.DuckDBPyConnection) -> dict:
    orders_per_day = con.execute(
        """
        SELECT
            order_day,
            COUNT(*) AS row_count,
            ROUND(MEDIAN(amount), 2) AS amount_median,
            ROUND(AVG(amount), 2) AS amount_mean,
            ROUND(MIN(amount), 2) AS amount_min,
            ROUND(MAX(amount), 2) AS amount_max,
            ROUND(AVG(CASE WHEN amount IS NULL THEN 1.0 ELSE 0.0 END), 6) AS amount_null_rate,
            LIST(DISTINCT payment_processor ORDER BY payment_processor) AS payment_processors
        FROM staging.stg_orders
        GROUP BY order_day
        ORDER BY order_day
        """
    ).fetchall()

    customers = con.execute(
        """
        SELECT
            COUNT(*) AS row_count,
            AVG(CASE WHEN customer_id IS NULL THEN 1.0 ELSE 0.0 END) AS customer_id_null_rate,
            AVG(CASE WHEN segment IS NULL THEN 1.0 ELSE 0.0 END) AS segment_null_rate,
            LIST(DISTINCT segment ORDER BY segment) AS segments
        FROM staging.stg_customers
        """
    ).fetchone()

    fx = con.execute(
        """
        SELECT
            COUNT(*) AS row_count,
            AVG(CASE WHEN usd_rate IS NULL THEN 1.0 ELSE 0.0 END) AS usd_rate_null_rate,
            LIST(DISTINCT currency ORDER BY currency) AS currencies,
            ROUND(MIN(usd_rate), 6) AS usd_rate_min,
            ROUND(MAX(usd_rate), 6) AS usd_rate_max
        FROM staging.stg_fx_rates
        """
    ).fetchone()

    return {
        "stg_orders": {
            "per_day": [
                {
                    "day": str(d),
                    "row_count": int(n),
                    "amount_median": float(med),
                    "amount_mean": float(mean),
                    "amount_min": float(lo),
                    "amount_max": float(hi),
                    "amount_null_rate": float(nr),
                    "payment_processors": list(procs),
                }
                for d, n, med, mean, lo, hi, nr, procs in orders_per_day
            ]
        },
        "stg_customers": {
            "row_count": int(customers[0]),
            "customer_id_null_rate": float(customers[1]),
            "segment_null_rate": float(customers[2]),
            "segments": list(customers[3]),
        },
        "stg_fx_rates": {
            "row_count": int(fx[0]),
            "usd_rate_null_rate": float(fx[1]),
            "currencies": list(fx[2]),
            "usd_rate_min": float(fx[3]),
            "usd_rate_max": float(fx[4]),
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="faultline-baseline-") as td:
        tmp = Path(td)
        sources = tmp / "sources"
        warehouse = tmp / "warehouse"
        generate_sources.generate("healthy", sources, warehouse)
        builder.build(sources, warehouse)

        con = duckdb.connect(str(warehouse / "faultline.duckdb"), read_only=True)
        try:
            daily = _daily_revenue_baseline(con)
            profile = _profile_baseline(con)
        finally:
            con.close()

    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINES_DIR / "daily_revenue_baseline.json").write_text(json.dumps(daily, indent=2) + "\n")
    (BASELINES_DIR / "profile_baseline.json").write_text(json.dumps(profile, indent=2) + "\n")
    print(f"wrote baselines for {len(daily)} days -> {BASELINES_DIR}")


if __name__ == "__main__":
    main()
