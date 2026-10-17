"""Observed telemetry: per-minute error-rate windows MEASURED by a real monitoring backend (e.g. Prometheus span
metrics of a running system), written into a tenant graph the same way the simulator writes its windows, so the
product's normal run loop reads real telemetry through the same templates (Q-MW-1, the gate's G4/G5 reads, INTAKE).

    (:MetricWindow {target_id, metric:'error_rate', minute, at, value, kind:'live', source, calls})-[:WINDOW_OF]->(component)

The caller fetches the measurements (the system under observation is reached outside the graph); this module validates
them, records an (:Evidence) node for the batch first (source, query, time range, digest, row count, the components it
is about) and then writes the windows with writes.py. Unknown components and malformed rows fail loudly: nothing is
silently dropped or invented.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from falkordb import Graph

from ..graph import writes
from ..graph.ro import RO

MINUTE = 60_000


class ObservedTelemetryError(ValueError):
    """Rows that cannot be ingested as they are (unknown component, value out of range, unaligned minute)."""


def _labels(ro: RO, ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(ids), 100):   # one RO read per 100 ids (the template's LIMIT)
        res = ro.run("Q-LABELS-1", {"ids": ids[i:i + 100]})
        if res.truncated:
            raise RuntimeError("Q-LABELS-1 truncated on a 100-id chunk")
        out.update({r["id"]: r["label"] for r in res.rows})
    return out


def validate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row {target, at, value[, calls]}: at a whole minute (epoch ms), 0 ≤ value ≤ 1, one row per (target, at)."""
    seen: set[tuple[str, int]] = set()
    out = []
    for r in rows:
        t, at, v = r.get("target"), r.get("at"), r.get("value")
        if not isinstance(t, str) or not t:
            raise ObservedTelemetryError(f"row without a component id: {r!r}")
        if not isinstance(at, int) or at % MINUTE:
            raise ObservedTelemetryError(f"{t}: window time {at!r} is not a whole minute in epoch ms")
        if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
            raise ObservedTelemetryError(f"{t}@{at}: error rate {v!r} outside [0, 1]")
        if (t, at) in seen:
            raise ObservedTelemetryError(f"{t}@{at}: two windows for one minute")
        seen.add((t, at))
        calls = r.get("calls")
        out.append({"target": t, "at": at, "value": round(float(v), 5), "calls": int(calls) if calls is not None else None})
    return out


def digest(rows: list[dict[str, Any]]) -> str:
    body = json.dumps(sorted(rows, key=lambda r: (r["target"], r["at"])), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def write_error_windows(g: Graph, ro: RO, *, rows: list[dict[str, Any]], onset_ms: int, source: str, query: str,
                        run: str) -> dict:
    """Validate, record the ingest Evidence, write the windows. Returns {windows, components, evidence, digest}."""
    t0 = time.perf_counter()
    rows = validate(rows)
    if not rows:
        raise ObservedTelemetryError("no telemetry rows to ingest")
    targets = sorted({r["target"] for r in rows})
    lbl = _labels(ro, targets)
    unknown = [t for t in targets if t not in lbl]
    if unknown:
        raise ObservedTelemetryError(f"components not in the graph: {', '.join(unknown)}")
    dg = digest(rows)
    ev = f"ev-ingest-{dg[:16]}"
    per = {t: sum(1 for r in rows if r["target"] == t) for t in targets}
    since, until = min(r["at"] for r in rows), max(r["at"] for r in rows)
    writes.record_external_evidence(
        g, run=run, tc_id=f"tc-{run}-ingest", tool="ingest_observed_telemetry", ev_id=ev, kind="telemetry_ingest",
        source=source, transport="http", params={"query": query, "since": since, "until": until, "onset": onset_ms},
        payload={"windows": len(rows), "per_component": per}, digest=dg, about=targets,
        summary=f"{len(rows)} per-minute error-rate windows for {len(targets)} components from {source}",
        ms=(time.perf_counter() - t0) * 1000, rows=len(rows))
    mw = [{"id": f"mw-{r['target']}-error_rate-{r['at']}", "target_id": r["target"], "metric": "error_rate",
           "minute": round((r["at"] - onset_ms) / MINUTE), "at": r["at"], "value": r["value"], "kind": "live",
           "source": source, "calls": r["calls"], "evidence_id": ev} for r in rows]
    writes.upsert_nodes(g, "MetricWindow", mw)
    by_label: dict[str, list[dict]] = {}
    for r in mw:
        by_label.setdefault(lbl[r["target_id"]], []).append({"src": r["id"], "dst": r["target_id"]})
    for label, pairs in by_label.items():
        writes.upsert_edges(g, "WINDOW_OF", "MetricWindow", label, pairs)
    return {"windows": len(mw), "components": len(targets), "evidence": ev, "digest": dg}
