"""Deterministic warehouse operations. All numbers shown in the UI or cited as
evidence come from here (or FalkorDB) — never from LLM text."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import duckdb

from .config import REPO_ROOT, settings
from .models import DailyPoint, MetricSnapshot, TestFailure, TestReport

_READONLY_RE = re.compile(r"^\s*(select|with|describe|show|explain)\b", re.IGNORECASE)


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    # Read-only protects the DB file, NOT the filesystem: without this, a
    # SELECT-prefixed query could still exfiltrate local files via read_csv()/
    # read_text() etc. (found by security review — prompt-injection hardening).
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    return con


_EXTERNAL_FN_RE = re.compile(
    r"\b(read_csv|read_csv_auto|read_text|read_blob|read_json|read_json_auto|read_parquet|"
    r"parquet_scan|glob|copy|attach|install|load|getenv)\b",
    re.IGNORECASE,
)


def run_sql(query: str, limit: int = 50) -> dict[str, Any]:
    """Read-only SQL against the demo warehouse."""
    if not _READONLY_RE.match(query):
        raise ValueError("only read-only queries (SELECT/WITH/DESCRIBE/SHOW/EXPLAIN) are allowed")
    if ";" in query.rstrip().rstrip(";"):
        raise ValueError("multiple statements are not allowed")
    if _EXTERNAL_FN_RE.search(query):
        raise ValueError("filesystem/external-access functions are not allowed in warehouse queries")
    with _connect() as con:
        rel = con.sql(query)
        cols = rel.columns
        rows = rel.fetchmany(limit)
    return {
        "columns": cols,
        "rows": [[_json_safe(v) for v in row] for row in rows],
        "row_count_returned": len(rows),
        "truncated_at": limit,
    }


def _json_safe(v: Any) -> Any:
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def profile_column(
    table: str, column: str, segment_by: str | None = None, last_days: int = 14
) -> dict[str, Any]:
    """Per-day stats for a numeric column, optionally segmented (e.g. by payment_processor).

    This is the primary evidence generator: it exposes distribution shifts without
    knowing anything about the specific incident.
    """
    _validate_ident(table)
    _validate_ident(column)
    ts_col = _pick_time_column(table)
    seg_expr = "'all'"
    if segment_by:
        _validate_ident(segment_by)
        seg_expr = segment_by
    q = f"""
        SELECT CAST({ts_col} AS DATE) AS day,
               {seg_expr} AS segment,
               COUNT(*) AS n,
               ROUND(AVG({column}), 4) AS mean,
               ROUND(MEDIAN({column}), 4) AS median,
               ROUND(MIN({column}), 4) AS min,
               ROUND(MAX({column}), 4) AS max,
               ROUND(AVG(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END), 4) AS null_rate
        FROM {table}
        GROUP BY 1, 2
        ORDER BY 1 DESC, 2
    """
    with _connect() as con:
        max_day = con.sql(f"SELECT MAX(CAST({ts_col} AS DATE)) FROM {table}").fetchone()[0]
        rows = con.sql(q).fetchall()
    cutoff = None
    if max_day is not None:
        import datetime as _dt

        cutoff = max_day - _dt.timedelta(days=last_days - 1)
    out = []
    for day, seg, n, mean, median, mn, mx, null_rate in rows:
        if cutoff is not None and day < cutoff:
            continue
        out.append(
            {
                "day": str(day),
                "segment": seg,
                "n": n,
                "mean": mean,
                "median": median,
                "min": mn,
                "max": mx,
                "null_rate": null_rate,
            }
        )
    return {"table": table, "column": column, "segment_by": segment_by, "days": out}


def compare_to_baseline(last_days: int = 10) -> dict[str, Any]:
    """Compare current daily revenue/AOV against the committed healthy baselines."""
    baseline_path = settings.baselines_dir / "daily_revenue_baseline.json"
    baseline = {r["day"]: r for r in json.loads(baseline_path.read_text())}
    with _connect() as con:
        rows = con.sql(
            "SELECT CAST(day AS DATE) AS day, revenue_usd, order_count, aov_median_usd "
            "FROM marts.fct_revenue ORDER BY day DESC LIMIT ?",
            params=[last_days],
        ).fetchall()
    comparisons = []
    for day, revenue, n, aov in rows:
        b = baseline.get(str(day))
        comparisons.append(
            {
                "day": str(day),
                "revenue_usd": round(revenue, 2),
                "baseline_revenue_usd": round(b["revenue_usd"], 2) if b else None,
                "revenue_ratio": round(revenue / b["revenue_usd"], 3) if b and b["revenue_usd"] else None,
                "aov_median_usd": round(aov, 2),
                "baseline_aov_median_usd": round(b["aov_median_usd"], 2) if b else None,
                "aov_ratio": round(aov / b["aov_median_usd"], 3) if b and b["aov_median_usd"] else None,
                "order_count": n,
                "baseline_order_count": b["order_count"] if b else None,
            }
        )
    return {"comparisons": comparisons, "baseline_source": str(baseline_path.relative_to(REPO_ROOT))}


def get_metric_snapshot() -> MetricSnapshot:
    raw = json.loads(settings.metric_snapshot_path.read_text())
    baseline_path = settings.baselines_dir / "daily_revenue_baseline.json"
    baseline = {}
    if baseline_path.exists():
        baseline = {r["day"]: r["revenue_usd"] for r in json.loads(baseline_path.read_text())}
    daily = [
        DailyPoint(day=d["day"], revenue_usd=d["revenue_usd"], baseline=baseline.get(d["day"]))
        for d in raw.get("daily", [])
    ]
    ratio = raw["anomaly_ratio"]
    return MetricSnapshot(
        kpi_day=raw["kpi_day"],
        revenue=raw["revenue"],
        expected_revenue=raw["expected_revenue"],
        anomaly_ratio=ratio,
        status="anomalous" if (ratio > 1.5 or ratio < 0.6) else "ok",
        daily=daily,
    )


def read_transform(name: str) -> dict[str, str]:
    """Read a transformation's SQL source (path-safe)."""
    fname = Path(name).name
    if not fname.endswith(".sql"):
        fname += ".sql"
    path = settings.transforms_dir / fname
    if not path.exists():
        available = sorted(p.name for p in settings.transforms_dir.glob("*.sql"))
        raise FileNotFoundError(f"unknown transform {fname!r}; available: {available}")
    return {"file": str(path.relative_to(REPO_ROOT)), "sql": path.read_text()}


def list_transforms() -> list[str]:
    return sorted(p.name for p in settings.transforms_dir.glob("*.sql"))


def statement_types(sql: str) -> list[str]:
    """DuckDB's own split of `sql` into statements, by type name (CREATE, COPY, SET, …), without running anything.
    ValueError when it does not parse."""
    try:
        return [st.type.name for st in duckdb.extract_statements(sql)]
    except duckdb.Error as e:
        raise ValueError(str(e).splitlines()[0][:160]) from None


def scrubbed_env() -> dict[str, str]:
    """The environment for pipeline subprocesses (review round 5, M4): they run SQL an LLM may have authored, so they
    get nothing of the API's environment (no API keys, no FalkorDB or GitHub credentials): only what Python needs."""
    import os

    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
           "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


def run_step(cmd: list[str], *, what: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run one pipeline step with this interpreter (`sys.executable`: the prod image has no `uv` dev tooling) and a
    scrubbed environment. A failure raises RuntimeError with a generic message; the step's stderr (paths, SQL) goes to
    the server log under a request id, never into a client-visible note."""
    import logging
    import uuid

    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, env=scrubbed_env())
    if proc.returncode != 0:
        rid = uuid.uuid4().hex[:12]
        logging.getLogger("faultline.warehouse").error("request %s: %s failed (exit %s): %s", rid, what, proc.returncode,
                                                       (proc.stderr or proc.stdout or "")[-2000:])
        raise RuntimeError(f"{what} failed (exit {proc.returncode}; detail logged under request id {rid})")
    return proc


def rebuild_warehouse() -> dict[str, Any]:
    """Re-run the pipeline (transforms currently on disk) against the source CSVs. The build goes to a temporary DuckDB
    file that replaces the warehouse only when it succeeded (pipeline/run.py), so a failed build leaves the last good
    warehouse in place."""
    import sys

    try:
        proc = run_step([sys.executable, "pipeline/run.py"], what="warehouse rebuild", timeout=300)
    except RuntimeError as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}
    return {"ok": True, "stdout": proc.stdout[-2000:], "stderr": ""}


def sources_sha256() -> str:
    """One digest over the fixture's source CSVs (name + bytes, sorted): what the warehouse was built from."""
    import hashlib

    h = hashlib.sha256()
    for p in sorted(settings.sources_dir.glob("raw_*.csv")):
        h.update(p.name.encode() + b"\0")
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def fixture_state() -> dict[str, str]:
    """The fixture the warehouse is in now: its mode (written by pipeline/generate_sources.py) and the sources digest.
    A data repair records it in its plan (bound by the plan hash) and re-establishes it before applying and verifying
    (review round 5, M2), so a repair is never verified against another run's data."""
    mode_file = settings.warehouse_path.parent / ".fixture_mode"
    mode = mode_file.read_text().strip() if mode_file.exists() else ""
    return {"mode": mode, "sources_sha256": sources_sha256()}


def run_invariants() -> TestReport:
    """Run the pipeline invariant suite; parse structured results from junit xml."""
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        xml_path = f.name
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "pipeline/invariants", "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        env=scrubbed_env(),
    )
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return TestReport(
            total=0, passed=0, failed=1,
            failures=[TestFailure(name="pytest", message="invariant suite produced no junit report (exit "
                                  f"{proc.returncode}); see the server log")],
        )
    finally:
        Path(xml_path).unlink(missing_ok=True)
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    total = int(suite.get("tests", 0))
    errors = int(suite.get("errors", 0))
    failed = int(suite.get("failures", 0)) + errors
    skipped = int(suite.get("skipped", 0))
    failures = []
    for case in suite.iter("testcase"):
        for bad in list(case.iter("failure")) + list(case.iter("error")):
            failures.append(
                TestFailure(
                    name=f"{case.get('classname', '')}::{case.get('name', '')}",
                    message=(bad.get("message") or "")[:400],
                )
            )
    return TestReport(total=total, passed=total - failed - skipped, failed=failed, failures=failures)


# -- helpers ------------------------------------------------------------------

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _validate_ident(ident: str) -> None:
    if not _IDENT_RE.match(ident):
        raise ValueError(f"invalid identifier: {ident!r}")


_TIME_COLUMNS = ["order_ts", "day", "date", "created_at", "rate_date"]


def _pick_time_column(table: str) -> str:
    with _connect() as con:
        cols = [r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()]
    for c in _TIME_COLUMNS:
        if c in cols:
            return c
    raise ValueError(f"no known time column in {table}; columns={cols}")
