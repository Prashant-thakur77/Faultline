"""Export a run FROM THE GRAPH into examples/<name>/ (events.jsonl, gate_runs.json, tool_calls.json,
hypotheses.json, report.md, report.json). These files are exports for replay and judges; the graph is
the record. Usage: python scripts/export_run.py --graph eval_acme_… --incident inc-… --run run-… --out examples/s2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faultline.agent import report
from faultline.graph.ro import RO


def export(tenant: str, graph: str, inc: str, run: str, out: Path, outcome: str) -> dict:
    ro = RO(tenant, graph)
    out.mkdir(parents=True, exist_ok=True)
    stages = ro.run("Q-RUN-1", {"run": run}).rows
    calls = ro.run("Q-RUN-2", {"run": run}).rows
    gates = ro.run("Q-INC-GATES", {"inc": inc}).rows
    hyps = ro.run("Q-HYP-1", {"inc": inc}).rows
    events = sorted([{"type": "stage", **s} for s in stages] + [{"type": "tool_call", **c} for c in calls]
                    + [{"type": "gate_run", **{**g, "checks": json.loads(g["checks"])}} for g in gates],
                    key=lambda e: (e.get("at") or 0, e.get("id") or ""))
    (out / "events.jsonl").write_text("".join(json.dumps(e, default=str) + "\n" for e in events))
    (out / "gate_runs.json").write_text(json.dumps([{**g, "checks": json.loads(g["checks"])} for g in gates], indent=2, default=str))
    (out / "tool_calls.json").write_text(json.dumps(calls, indent=2, default=str))
    (out / "hypotheses.json").write_text(json.dumps(hyps, indent=2, default=str))
    rep = report.build(tenant, graph, inc, outcome)
    (out / "report.json").write_text(rep.model_dump_json(indent=2))
    (out / "report.md").write_text(report.to_markdown(rep))
    return {"events": len(events), "gate_runs": len(gates), "tool_calls": len(calls)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--incident", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--outcome", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(export(a.tenant, a.graph, a.incident, a.run, Path(a.out), a.outcome))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
