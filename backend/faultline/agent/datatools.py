"""Data tools: the warehouse and pipeline tools (the system under observation), wrapped so every
observation is recorded as (:Evidence)-[:ABOUT]->(graph node) in FalkorDB BEFORE anything uses it.

Numbers (ratios, bands, shares) are computed here in code from the warehouse and the committed
healthy baselines — never by the model. Table names in the warehouse are the graph ids of
(:Table) nodes (e.g. `staging.stg_orders`), so evidence attaches to the lineage graph directly.
"""

from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from .. import warehouse
from ..graph import client, writes
from ..graph.errors import GraphError
from ..graph.ro import RO
from ..mcp_server import context
from . import unit_shift
from .weights import weights

KPI_ID = "kpi.exec_revenue"
KPI_TABLE = "marts.exec_revenue_metric"
FACT_TABLE = "marts.fct_revenue"


def _ro() -> RO:
    b = context.current()
    return RO(b.tenant, b.graph)


def baseline_series(target: str, metric: str) -> list[float]:
    """Healthy baseline values of a metric, read from the graph (Q-BASE-1)."""
    return [float(r["value"]) for r in _ro().run("Q-BASE-1", {"target": target, "metric": metric}).rows]


def column_range(column_id: str) -> tuple[float, float]:
    rows = _ro().run("Q-BASE-2", {"column": column_id}).rows
    if not rows:
        raise KeyError(f"no healthy baseline in the graph for column {column_id}")
    return float(rows[0]["min"]), float(rows[0]["max"])


def engine_band(template: str, params: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """The gate's band computed IN FalkorDB (M20 #4): Q-BASE-BAND (a healthy baseline series) or Q-MW-BAND (a
    component's pre-onset error-rate windows) aggregate avg / stDevP / percentileCont over the nonzero windows and return
    max(floor, 1 + k·σ/μ) (floor when fewer than two). The same rule as `band_from`, which stays the reference (and the
    equality oracle in tests/live/test_band_in_engine.py); only the 4-place rounding stays in Python (Cypher's round
    breaks ties away from zero, Python's to even). Returns (band, what the engine reported, for the evidence)."""
    g = weights()["gate"]
    r = _ro().run(template, {**params, "k": float(g["band_k"]), "floor": float(g["band_floor"])})
    row = r.rows[0]
    # (no timing in it: the evidence id hashes the payload, and the same observation must keep the same id)
    return round(float(row["band"]), 4), {"template": template, "n": row["n_nz"], "mu": row["mu"], "sd": row["sd"],
                                          "p95": row["p95"]}


def band_from(values: list[float]) -> float:
    """band = max(floor, 1 + k·σ/μ) over a baseline window (weights.yaml gate.band_k / band_floor)."""
    g = weights()["gate"]
    vals = [v for v in values if v]
    if len(vals) < 2:
        return float(g["band_floor"])
    mu, sd = statistics.fmean(vals), statistics.pstdev(vals)
    return round(max(float(g["band_floor"]), 1.0 + float(g["band_k"]) * (sd / mu if mu else 0.0)), 4)


ABS_TOL = 0.005  # an excess below half a percentage point is in band whatever the band factor


def in_band(v: float, base: float, band: float, allowance: float = 0.0) -> bool:
    """VERIFY's in-band rule, shared with the futures prediction so the two can never drift apart: within the band
    factor of the baseline, or less than ABS_TOL above it (plus what other open incidents may still own)."""
    return v <= base * band + allowance or (v - base) < ABS_TOL + allowance


# the ToolCall id the last _record wrote in this context (set and read within one synchronous tool call, so concurrent
# specialists, each in its own task context, never see each other's): the wrapper returns it as `tool_call_id`
_last_call: contextvars.ContextVar[str | None] = contextvars.ContextVar("faultline_last_tool_call", default=None)


def _record(tool: str, kind: str, payload: Any, about: list[str], summary: str, params: dict, ms: float,
            value: float | None = None, baseline: float | None = None, ratio: float | None = None,
            band: float | None = None, transport: str = "duckdb", anomalous: bool | None = None,
            source: str = "warehouse") -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    ev = "ev_" + hashlib.sha256(f"{tool}|{sorted(params.items())}|{digest}".encode()).hexdigest()[:10]
    b = context.current()
    if b.run_id and b.record:
        g = client.engine().select_graph(b.graph)
        tc_id = b.next_call_id()
        _last_call.set(tc_id)
        writes.record_external_evidence(
            g, run=b.run_id, tc_id=tc_id, tool=tool, ev_id=ev, kind=kind, source=source,
            transport=transport, params=params, payload=payload, digest=digest, about=about, summary=summary,
            ms=ms, rows=len(payload) if isinstance(payload, list) else 1, value=value, baseline=baseline,
            ratio=ratio, band=band, anomalous=anomalous)
    return ev


def _tool(fn: Callable[..., dict]) -> Callable[..., dict]:
    @functools.wraps(fn)
    def wrapper(**kwargs: Any) -> dict:
        try:
            _last_call.set(None)
            out = fn(**kwargs)
            tc = _last_call.get()
            return {**out, "tool_call_id": tc} if tc and isinstance(out, dict) else out   # the agent links it (MADE)
        except GraphError as e:  # baselines live in the graph: with FalkorDB off there is no band
            return {"error": f"unavailable: {e}"}
        except (ValueError, FileNotFoundError, KeyError) as e:
            return {"error": f"{type(e).__name__}: {e}"}
        except Exception as e:  # warehouse failures are reported, never crash the loop
            return {"error": f"{type(e).__name__}: {e}"}
    return wrapper


@_tool
def get_metric_history() -> dict:
    """The executive KPI vs its trailing baseline (anomaly ratio, band from baseline variation)."""
    t0 = time.perf_counter()
    snap = warehouse.get_metric_snapshot()
    band, _ = engine_band("Q-BASE-BAND", {"target": FACT_TABLE, "metric": "revenue_usd"})   # in FalkorDB (M20 #4)
    payload = snap.model_dump()
    ev = _record("get_metric_history", "metric", payload, [KPI_ID, KPI_TABLE],
                 f"KPI {snap.kpi_day}: {snap.revenue:,.0f} vs expected {snap.expected_revenue:,.0f} (×{snap.anomaly_ratio:.2f}, band {band})",
                 {}, (time.perf_counter() - t0) * 1000, value=snap.revenue, baseline=snap.expected_revenue,
                 ratio=snap.anomaly_ratio, band=band, anomalous=_outside(snap.anomaly_ratio, band))
    return {"evidence_id": ev, "metric": payload, "band": band, "anomalous": _outside(snap.anomaly_ratio, band)}


def _outside(ratio: float | None, band: float) -> bool:
    import math

    return bool(ratio) and abs(math.log(ratio)) > math.log(band)


@_tool
def compare_to_baseline(last_days: int = 10) -> dict:  # noqa: D401
    """Recent daily revenue vs the committed healthy baseline (ratio per day; band from baseline σ/μ)."""
    last_days = max(1, min(int(last_days), 30))
    t0 = time.perf_counter()
    res = warehouse.compare_to_baseline(last_days=last_days)
    band, _ = engine_band("Q-BASE-BAND", {"target": FACT_TABLE, "metric": "revenue_usd"})   # in FalkorDB (M20 #4)
    ratios = [c["revenue_ratio"] for c in res["comparisons"] if c["revenue_ratio"]]
    worst = max(ratios, key=lambda r: abs(__import__("math").log(r))) if ratios else None
    anomalous_days = [c["day"] for c in res["comparisons"] if c["revenue_ratio"] and _outside(c["revenue_ratio"], band)]
    ev = _record("compare_to_baseline", "baseline_comparison", res["comparisons"], [FACT_TABLE],
                 f"worst day ratio ×{worst} (band {band}); anomalous days: {anomalous_days or 'none'}",
                 {"last_days": last_days}, (time.perf_counter() - t0) * 1000, ratio=worst, band=band,
                 anomalous=bool(anomalous_days))
    return {"evidence_id": ev, **res, "band": band, "anomalous_days": anomalous_days}


@_tool
def profile_column(table: str, column: str, segment_by: str | None = None, last_days: int = 14) -> dict:
    """Per-day stats of a column, optionally segmented (e.g. by payment_processor)."""
    t0 = time.perf_counter()
    res = warehouse.profile_column(table, column, segment_by=segment_by, last_days=int(last_days))
    about = [table, f"{table}.{column}"] + ([f"{table}.{segment_by}"] if segment_by else [])
    ev = _record("profile_column", "profile", res["days"], about,
                 f"profile {table}.{column}{' by ' + segment_by if segment_by else ''}: {len(res['days'])} day×segment rows",
                 {"table": table, "column": column, "segment_by": segment_by, "last_days": last_days},
                 (time.perf_counter() - t0) * 1000)
    return {"evidence_id": ev, **res}


@_tool
def baseline_columns(tables: list[str]) -> dict:
    """Which columns of these tables have a committed healthy baseline, i.e. what anomalous_row_share can measure
    (Q-BASE-3, read from the graph and recorded as evidence of what the data channel could see)."""
    if not isinstance(tables, list) or not tables or len(tables) > 50 or not all(isinstance(t, str) for t in tables):
        raise ValueError("tables must be a list of 1..50 table ids")
    for t in tables:
        warehouse._validate_ident(t)
    t0 = time.perf_counter()
    r = _ro().run("Q-BASE-3", {"tables": sorted(set(tables))})
    payload = [{k: row[k] for k in ("table", "column", "name", "min", "max")} for row in r.rows]
    ev = _record("baseline_columns", "baseline", payload, sorted({x["table"] for x in payload}) or sorted(set(tables)),
                 f"{len(payload)} baselined columns in {len(set(tables))} tables", {"tables": sorted(set(tables))},
                 (time.perf_counter() - t0) * 1000, transport="falkordb (Q-BASE-3)", source="falkordb")
    return {"evidence_id": ev, "rows": payload, "template": "Q-BASE-3"}


@_tool
def anomalous_row_share(table: str, column: str, day: str) -> dict:
    """Share of `table` rows on `day` whose `column` lies outside the committed healthy baseline's
    observed range for that column. This is the observed impact share on a data symptom (gate G5)."""
    warehouse._validate_ident(table)
    warehouse._validate_ident(column)
    lo, hi = column_range(f"{table}.{column}")
    ts = warehouse._pick_time_column(table)
    t0 = time.perf_counter()
    q = (f"SELECT count(*), sum(CASE WHEN {column} < {float(lo)} OR {column} > {float(hi)} THEN 1 ELSE 0 END) "  # noqa: S608
         f"FROM {table} WHERE CAST({ts} AS DATE) = DATE '{_iso_day(day)}'")
    with warehouse._connect() as con:
        n, bad = con.sql(q).fetchone()
    share = round((bad or 0) / n, 4) if n else 0.0
    payload = {"table": table, "column": column, "day": day, "rows": n, "outside": bad or 0,
               "baseline_range": [lo, hi], "share": share}
    ev = _record("anomalous_row_share", "row_share", payload, [table, f"{table}.{column}"],
                 f"{bad or 0}/{n} rows of {table}.{column} on {day} outside baseline range [{lo}, {hi}] → share {share}",
                 {"table": table, "column": column, "day": day}, (time.perf_counter() - t0) * 1000, value=share,
                 anomalous=share >= float(weights()["gate"]["row_share_min"]))
    return {"evidence_id": ev, **payload}


def _iso_day(day: str) -> str:
    import datetime as dt

    return dt.date.fromisoformat(str(day)[:10]).isoformat()


@_tool
def unit_shift_check(table: str, column: str, day: str) -> dict:
    """Is the anomaly in `table.column` on `day` ONE segment's unit shift? Every text column of the table with at
    most repair.segment_max_values distinct values that day is tried as a segment: per value, its rows, how many lie
    outside the column's healthy baseline range (the graph's Q-BASE-2), their median, and the complement's (the
    other values that day, or the 14 days before when the day has no other rows). The rule (agent/unit_shift.py
    find_shift, thresholds in weights.yaml `repair`) names the segment whose rows are nearly all outside, hold nearly
    all the outside rows, whose complement is clean, and whose median is 10^k the complement's. Recorded as Evidence
    (anomalous = a shift was found). What a keyless data repair starts from: a measurement, not a guess."""
    warehouse._validate_ident(table)
    warehouse._validate_ident(column)
    if table.count(".") != 1:
        raise ValueError("table must be schema.table")
    lo, hi = column_range(f"{table}.{column}")
    ts = warehouse._pick_time_column(table)
    d = _iso_day(day)
    w = weights()["repair"]
    purity = float(w["segment_purity"])
    t0 = time.perf_counter()
    schema, name = table.split(".", 1)
    outside = f"CASE WHEN {column} < {float(lo)} OR {column} > {float(hi)} THEN 1 ELSE 0 END"  # noqa: S608
    on_day = f"CAST({ts} AS DATE) = DATE '{d}'"
    before = f"CAST({ts} AS DATE) BETWEEN DATE '{d}' - 14 AND DATE '{d}' - 1"
    segments: list[dict] = []
    with warehouse._connect() as con:
        total = con.execute(f"SELECT count(*), sum({outside}) FROM {table} WHERE {on_day}").fetchone()  # noqa: S608
        total_rows, total_outside = int(total[0] or 0), int(total[1] or 0)
        cols = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ? "
            "AND data_type ILIKE '%CHAR%' ORDER BY ordinal_position", [schema, name]).fetchall()]
        for c in cols:
            warehouse._validate_ident(c)
            if c == column:
                continue
            k = con.execute(f"SELECT count(DISTINCT {c}) FROM {table} WHERE {on_day}").fetchone()[0]  # noqa: S608
            if not k or int(k) > int(w["segment_max_values"]):
                continue
            rows = con.execute(f"SELECT {c}, count(*), sum({outside}), median({column}) FROM {table} "  # noqa: S608
                               f"WHERE {on_day} AND {c} IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
            for v, n, out, med in rows:
                v = str(v)
                o = con.execute(f"SELECT count(*), sum({outside}), median({column}) FROM {table} "  # noqa: S608
                                f"WHERE {on_day} AND ({c} IS NULL OR {c} <> ?)", [v]).fetchone()
                basis = "other values that day"
                if not o[0]:   # the day holds no other value: the other values over the 14 days before (never this one)
                    o = con.execute(f"SELECT count(*), sum({outside}), median({column}) FROM {table} "  # noqa: S608
                                    f"WHERE {before} AND ({c} IS NULL OR {c} <> ?)", [v]).fetchone()
                    basis = "other values, the 14 days before"
                first = con.execute(f"SELECT min(dd) FROM (SELECT CAST({ts} AS DATE) AS dd, avg({outside}) AS sh FROM {table} "  # noqa: S608
                                    f"WHERE {c} = ? GROUP BY 1) WHERE sh >= ?", [v, purity]).fetchone()[0]
                existed_before = 0
                if first is not None:
                    existed_before = con.execute(f"SELECT count(*) FROM {table} WHERE {c} = ? AND CAST({ts} AS DATE) < DATE '{first}'",  # noqa: S608
                                                 [v]).fetchone()[0]
                segments.append({"segment": c, "value": v, "n": int(n), "outside": int(out or 0),
                                 "median": float(med) if med is not None else None, "other_n": int(o[0] or 0),
                                 "other_outside": int(o[1] or 0), "other_median": float(o[2]) if o[2] is not None else None,
                                 "other_basis": basis, "total_outside": total_outside,
                                 "since_day": str(first) if first is not None else None,
                                 "existed_before": bool(existed_before)})
    hit = unit_shift.find_shift(segments, tolerance=float(w["unit_shift_tolerance"]), purity=purity,
                                min_rows=int(w["segment_min_rows"]))
    payload = {"table": table, "column": column, "day": d, "time_column": ts, "baseline_range": [lo, hi],
               "rows": total_rows, "total_outside": total_outside, "segments": segments[:50], "shift": hit,
               "rule": {k: w[k] for k in ("unit_shift_tolerance", "segment_purity", "segment_min_rows", "segment_max_values")}}
    about = [table, f"{table}.{column}"] + ([f"{table}.{hit['segment']}"] if hit else [])
    summary = (f"unit shift on {table}.{column} ({d}): rows with {hit['segment']} = {hit['value']!r} are "
               f"{hit['factor']:.1f}× the others (10^{hit['power']}), {hit['outside']}/{hit['n']} outside the healthy range"
               if hit else f"no single segment of {table} carries the {total_outside}/{total_rows} outside rows on {d} as a unit shift")
    ev = _record("unit_shift_check", "unit_shift", payload, about, summary, {"table": table, "column": column, "day": d},
                 (time.perf_counter() - t0) * 1000, value=hit["factor"] if hit else None, ratio=hit["factor"] if hit else None,
                 anomalous=bool(hit))
    return {"evidence_id": ev, **payload}


@_tool
def run_sql(query: str) -> dict:
    """Read-only SQL against the warehouse (sandboxed: SELECT/WITH only, no external access)."""
    t0 = time.perf_counter()
    res = warehouse.run_sql(query)
    ev = _record("run_sql", "sql", res["rows"], [], f"ad-hoc SQL: {query.strip()[:160]}", {"query": query[:2000]},
                 (time.perf_counter() - t0) * 1000)
    return {"evidence_id": ev, **res}


@_tool
def list_transforms() -> dict:
    """List the pipeline's transform files (graph ids of (:Transform))."""
    return {"transforms": warehouse.list_transforms()}


@_tool
def read_transform(name: str) -> dict:
    """Read a transform's SQL source."""
    t0 = time.perf_counter()
    res = warehouse.read_transform(name)
    tid = Path(res["file"]).name
    ev = _record("read_transform", "sql", res, [tid], f"source of {tid}", {"name": name}, (time.perf_counter() - t0) * 1000)
    return {"evidence_id": ev, **res}


@_tool
def run_invariants() -> dict:
    """Run the pipeline's invariant suite (pytest) against the current warehouse."""
    t0 = time.perf_counter()
    report = warehouse.run_invariants()
    payload = report.model_dump()
    ev = _record("run_invariants", "test", payload, [], f"invariants {report.passed}/{report.total} passed", {},
                 (time.perf_counter() - t0) * 1000, value=float(report.passed), baseline=float(report.total),
                 transport="pytest")
    return {"evidence_id": ev, **payload}


def error_rate_anomalous(v: float, b: float, band: float) -> bool:
    """metric_window's rule: at least gate.err_abs_min above the baseline AND outside the baseline band. A rise from an
    exactly-zero baseline is outside every band (its ratio is infinite). FaultBench-OTel found this on real telemetry:
    healthy services there report exactly 0 errors (the simulator never does), and the old rule (`bool(ratio) and …`,
    ratio None when the baseline is 0) called any rise from zero normal, so the negative proof accepted NO_INCIDENT."""
    if v - b < float(weights()["gate"]["err_abs_min"]):
        return False
    return True if b <= 0 else _outside(v / b, band)


@_tool
def metric_window(target_id: str, onset_ms: int) -> dict:
    """Error rate of a service/datastore around onset vs its pre-onset baseline (telemetry read from the graph).
    Records an error_rate measurement: value = mean over [onset−3m, onset], baseline = mean over
    [onset−30m, onset−5m]; anomalous when outside the baseline band AND ≥ err_abs_min above baseline."""
    import statistics as st

    t0 = time.perf_counter()
    onset = int(onset_ms)
    rows = _ro().run("Q-MW-1", {"target": target_id, "metric": "error_rate", "since": onset - 30 * 60_000,
                                "until": onset}).rows
    base = [r["value"] for r in rows if r["at"] <= onset - 5 * 60_000]
    now = [r["value"] for r in rows if r["at"] >= onset - 3 * 60_000]
    if not base or not now:
        raise KeyError(f"no telemetry windows for {target_id} around onset")
    b, v = st.fmean(base), st.fmean(now)
    # the band over the same baseline windows, computed in FalkorDB (Q-MW-BAND; M20 #4)
    band, band_engine = engine_band("Q-MW-BAND", {"target": target_id, "metric": "error_rate",
                                                  "since": onset - 30 * 60_000, "until": onset - 5 * 60_000})
    ratio = v / b if b else None
    anomalous = error_rate_anomalous(v, b, band)
    # observed windows (faultline.ingest.observed) name their monitoring source; simulated ones carry none
    src = next((r["source"] for r in rows if r.get("source")), None)
    src, via = (src, "observed telemetry ingested into the graph") if src else ("simulator", "servicegraph (simulated)")
    payload = {"target": target_id, "baseline": round(b, 5), "now": round(v, 5), "ratio": round(ratio, 3) if ratio else None,
               "band": band, "band_engine": band_engine, "series": [[r["minute"], r["value"]] for r in rows][-12:]}
    ev = _record("metric_window", "error_rate", payload, [target_id],
                 f"{target_id} error rate {v:.2%} vs baseline {b:.2%} (×{ratio:.1f}, band {band})" if ratio else f"{target_id} error rate {v:.2%}",
                 {"target_id": target_id, "onset_ms": onset}, (time.perf_counter() - t0) * 1000, value=round(v, 5),
                 baseline=round(b, 5), ratio=ratio, band=band, anomalous=anomalous, source=src, transport=via)
    return {"evidence_id": ev, **payload, "anomalous": anomalous}


TOOLS: dict[str, Callable[..., dict]] = {f.__name__: f for f in (
    metric_window,
    get_metric_history, compare_to_baseline, profile_column, baseline_columns, anomalous_row_share, run_sql, list_transforms,
    read_transform, run_invariants, unit_shift_check,
)}
