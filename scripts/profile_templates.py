"""PROFILE-check the queries the product actually runs.

Runs S1 (service hero) and S2 (data incident) on fresh GRAPH.COPY clean rooms with the deterministic investigator.
It then takes every template those runs executed, with the exact params recorded in the graph (tool-call evidence
and gate-check params), and runs GRAPH.PROFILE (graph/ro.py::profile) and the RO wrapper 5 times each on the same
graph. Writes docs/audit/profile.json; scripts/gen_query_catalogue.py adds the p50 columns to the catalogue. p50 and
p95 are nearest-rank percentiles over N runs (N = 20, so p95 is the 19th fastest of 20).

    PYTHONPATH=backend uv run python scripts/profile_templates.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

from faultline import scenario  # noqa: E402
from faultline.agent.loop import BaselineInvestigator  # noqa: E402
from faultline.graph import client  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO, profile  # noqa: E402

OUT = ROOT / "docs" / "audit" / "profile.json"
N = 20
# these run on a temporary engine-written projection (scratch graph), not on the incident graph: profiling them on
# the incident graph would measure a different query plan, so they are listed, not timed
SCRATCH = {"Q-RANK-1", "Q-ORG-HARM", "Q-ORG-MSF", "Q-STORM-WCC", "Q-STORM-ATTACH"}


def _pairs(ro: RO, run: str, inc: str) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for tc in ro.run("Q-RUN-2", {"run": run}).rows:
        if not (tc["template"] and tc["params"]):
            continue
        params = json.loads(tc["params"])
        parts = tc["template"].split("+")  # a combined evidence item ("Q-A+Q-B") keeps each part's params by id
        for tid in parts:
            p = params.get(tid) if len(parts) > 1 else params
            if tid not in seen and isinstance(p, dict):
                seen[tid] = p
    for gr in ro.run("Q-INC-GATES", {"inc": inc}).rows:
        for c in json.loads(gr["checks"]):
            if c.get("template") and c["template"] not in seen and c.get("params") is not None:
                seen[c["template"]] = c["params"]
    return seen


def pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q = 0.95 → the ceil(0.95·n)-th smallest)."""
    if not xs:
        return None
    import math

    xs = sorted(xs)
    return round(xs[max(0, math.ceil(q * len(xs)) - 1)], 3)


def collect() -> dict[str, dict]:
    """Run S1 + S2 clean rooms and PROFILE every template they executed (used by evals/harness.py too)."""
    results: dict[str, dict] = {}
    for sid, set_mode in (("S1", False), ("S2", True)):
        p, res = anyio.run(lambda: scenario.run(sid, BaselineInvestigator(), set_mode=set_mode, keep=True))
        try:
            ro = RO(p.tenant, p.graph)
            for tid, params in sorted(_pairs(ro, p.run_id, p.incident_id).items()):
                if tid in results or tid == "T2C":
                    continue
                if tid in SCRATCH:
                    results[tid] = {"scenario": sid, "runs": 0, "note": "runs on a temporary scratch projection; not timed here"}
                    continue
                engine, wall, rows, err = [], [], None, None
                for _ in range(N):
                    try:
                        engine.append(profile(p.tenant, tid, params, p.graph)["engine_ms"])
                        r = ro.run(tid, params)
                        wall.append(r.ms)
                        rows = len(r.rows)
                    except Exception as e:  # noqa: BLE001 - e.g. a template that ran on a deleted scratch graph
                        err = f"{type(e).__name__}: {str(e)[:120]}"
                        break
                results[tid] = {"scenario": sid, "runs": len(engine), "rows": rows,
                                "engine_ms_p50": round(statistics.median(engine), 3) if engine else None,
                                "engine_ms_p95": pct(engine, 0.95), "wall_ms_p50": round(statistics.median(wall), 3) if wall else None,
                                "wall_ms_p95": pct(wall, 0.95), **({"error": err} if err else {})}
                print(tid, results[tid])
        finally:
            gcopy.delete_if_exists(client.engine(), p.graph)
    scenario.set_pipeline_mode("incident")
    return results


def main() -> int:
    results = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    meta = json.loads((ROOT / "backend/faultline/graph/algo/resolved.json").read_text())
    OUT.write_text(json.dumps({"engine": meta["engine"], "digest": meta["digest"], "runs_per_template": N,
                               "templates": results}, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(results)} templates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
