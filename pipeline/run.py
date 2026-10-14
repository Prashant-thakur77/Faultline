"""Build the Faultline demo warehouse from data/sources CSVs.

Loads sources into DuckDB schema `raw`, runs SQL transforms into `staging`
and `marts`, and writes data/warehouse/metric_snapshot.json. Fully idempotent.

Safety (review round 5, M3/M4):
* the build goes to a temporary DuckDB file next to the warehouse and replaces it with one os.replace only when
  every step succeeded: a failed build (a bad transform) leaves the last good warehouse in place, and readers never
  see a half-built file;
* once the raw sources are loaded, external access is switched off and the configuration locked, so a transform (an
  LLM may have authored one) cannot read or write files, attach databases, install extensions or read the
  environment.
"""

import json
import os
from pathlib import Path

import duckdb

TRANSFORM_ORDER = [
    "stg_orders.sql",
    "stg_customers.sql",
    "stg_fx_rates.sql",
    "fct_revenue.sql",
    "exec_revenue_metric.sql",
]

RAW_TABLES = {
    # table -> (csv file, explicit column types; raw stays close to the wire)
    "raw_orders": (
        "raw_orders.csv",
        {
            "order_id": "VARCHAR",
            "order_ts": "VARCHAR",
            "customer_id": "VARCHAR",
            "currency": "VARCHAR",
            "amount": "DOUBLE",
            "payment_processor": "VARCHAR",
            "status": "VARCHAR",
        },
    ),
    "raw_customers": (
        "raw_customers.csv",
        {
            "customer_id": "VARCHAR",
            "name": "VARCHAR",
            "segment": "VARCHAR",
            "country": "VARCHAR",
            "created_at": "VARCHAR",
        },
    ),
    "raw_fx_rates": (
        "raw_fx_rates.csv",
        {
            "rate_day": "VARCHAR",
            "currency": "VARCHAR",
            "usd_rate": "DOUBLE",
        },
    ),
}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def build(sources_dir: Path, warehouse_dir: Path, transforms_dir: Path | None = None) -> dict:
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    db_path = warehouse_dir / "faultline.duckdb"
    tmp_path = warehouse_dir / f".faultline.duckdb.build-{os.getpid()}"
    for p in (tmp_path, tmp_path.with_name(tmp_path.name + ".wal")):
        p.unlink(missing_ok=True)
    transforms_dir = transforms_dir or Path(__file__).resolve().parent / "transforms"

    con = duckdb.connect(str(tmp_path))
    try:
        con.execute("SET TimeZone = 'UTC'")
        for schema in ("raw", "staging", "marts"):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        for table, (csv_name, columns) in RAW_TABLES.items():
            csv_path = sources_dir / csv_name
            if not csv_path.exists():
                raise FileNotFoundError(
                    f"{csv_path} missing — run `uv run python pipeline/generate_sources.py --mode incident` first"
                )
            cols_sql = json.dumps(columns)
            con.execute(
                f"CREATE OR REPLACE TABLE raw.{table} AS "
                f"SELECT * FROM read_csv(?, header = true, columns = {cols_sql})",
                [str(csv_path)],
            )

        # From here on the build only reads what is already in the database: no file, network or environment access,
        # and no way to switch it back on (the transforms are the only code that runs after this point).
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")

        for name in TRANSFORM_ORDER:
            con.execute((transforms_dir / name).read_text())

        metric = con.execute(
            "SELECT kpi_day, revenue, trailing_28d_median_revenue, anomaly_ratio "
            "FROM marts.exec_revenue_metric"
        ).fetchone()
        daily = con.execute(
            "SELECT day, revenue_usd, order_count, aov_median_usd "
            "FROM marts.fct_revenue ORDER BY day"
        ).fetchall()
    except BaseException:
        con.close()
        for p in (tmp_path, tmp_path.with_name(tmp_path.name + ".wal")):
            p.unlink(missing_ok=True)
        raise
    con.close()

    snapshot = {
        "kpi_day": str(metric[0]),
        "revenue": float(metric[1]),
        "expected_revenue": float(metric[2]),
        "anomaly_ratio": float(metric[3]),
        "daily": [
            {
                "day": str(d),
                "revenue_usd": float(rev),
                "order_count": int(cnt),
                "aov_median_usd": float(aov),
            }
            for d, rev, cnt, aov in daily
        ],
    }
    # swap the finished build in: the old warehouse's WAL (none after a clean close) must not be replayed onto it
    (warehouse_dir / "faultline.duckdb.wal").unlink(missing_ok=True)
    tmp_path.with_name(tmp_path.name + ".wal").unlink(missing_ok=True)
    os.replace(tmp_path, db_path)
    _atomic_write(warehouse_dir / "metric_snapshot.json", json.dumps(snapshot, indent=2) + "\n")
    return snapshot


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    snap = build(repo_root / "data" / "sources", repo_root / "data" / "warehouse")
    print(
        f"built warehouse: kpi_day={snap['kpi_day']} revenue={snap['revenue']:.2f} "
        f"expected={snap['expected_revenue']:.2f} anomaly_ratio={snap['anomaly_ratio']:.2f} "
        f"({len(snap['daily'])} days)"
    )


if __name__ == "__main__":
    main()
