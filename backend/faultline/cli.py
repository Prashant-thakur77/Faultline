"""Faultline CLI.

    python -m faultline.cli run --scenario S2 [--llm baseline|anthropic] [--keep]
"""

from __future__ import annotations

import argparse
import json
import sys

import anyio


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="faultline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario end to end in a GRAPH.COPY clean room")
    r.add_argument("--scenario", required=True)
    r.add_argument("--llm", choices=["baseline", "anthropic"], default="baseline",
                   help="baseline = deterministic rule-based investigator (no key); anthropic = live model")
    r.add_argument("--keep", action="store_true", help="keep the eval graph for inspection")
    r.add_argument("--no-mode", action="store_true", help="do not switch the warehouse fixture mode")
    r.add_argument("--export", help="export the run from the graph into this directory (e.g. examples/s2)")
    a = ap.parse_args(argv)
    from . import scenario
    from .agent.loop import BaselineInvestigator, LLMInvestigator

    inv = BaselineInvestigator() if a.llm == "baseline" else LLMInvestigator()
    p, res = anyio.run(lambda: scenario.run(a.scenario, inv, keep=True, set_mode=not a.no_mode))
    if a.export:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location("export_run", Path(__file__).resolve().parents[2] / "scripts" / "export_run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.export(p.tenant, p.graph, p.incident_id, p.run_id, Path(a.export), res.outcome)
    if not a.keep:
        from .graph import client as gclient
        from .graph import copy as gcopy

        gcopy.delete_if_exists(gclient.engine(), p.graph)
    gate = res.gate or {}
    out = {"scenario": a.scenario, "graph": p.graph, "incident": res.incident_id, "run": res.run_id,
           "outcome": res.outcome, "cause": res.cause_id, "confident": res.confident, "chain": gate.get("chain"),
           "sweep": [{k: v[k] for k in ("change", "status", "reason", "flow")} for v in res.sweep],
           "suspects": [{k: s[k] for k in ("id", "total", "hops")} for s in res.suspects],
           "tool_calls": res.tool_calls, "gate_attempts": res.gate_attempts, "investigator": res.investigator,
           "seconds": res.seconds, "error": res.error}
    print(json.dumps(out, indent=2, default=str))
    if res.trace:
        print(res.trace, file=sys.stderr)
    return 0 if not res.error else 1


if __name__ == "__main__":
    sys.exit(main())
