"""Regenerate evals/RESULTS.md, evals/results/latest.json and docs/NAIVE_VS_FAULTLINE.md from the newest
evals/results/run_*.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import report  # noqa: E402


def code_counts() -> dict:
    """The repo.* counts that describe the CODE (templates, MCP tools, hosted MCP tools, algorithms), read from the code
    now. They are not results of a run: taking them from the newest run left latest.json, and every tagged count,
    one template behind whenever a template or tool landed between eval runs (DECISIONS 2026-10-16). Tenant sizes stay
    the run's (they are read from the graphs the run used)."""
    sys.path.insert(0, str(ROOT / "backend"))
    from faultline.agent.phases import INTERNAL_TOOLS
    from faultline.graph.algo import registry
    from faultline.graph.templates import catalogue
    from faultline.mcp_server import tools as T

    from faultline.graph.constraints import CONSTRAINTS

    return {"repo.templates": len(catalogue()), "repo.algorithms": len(registry.resolved()), "repo.mcp_tools": len(T.TOOLS),
            "repo.mcp_tools_hosted": len([t for t in T.TOOLS if t not in INTERNAL_TOOLS]),
            # engine-enforced invariants (M20 #1): MANDATORY / UNIQUE constraints on nodes and relationships
            "repo.constraints": len(CONSTRAINTS)}


def main() -> int:
    runs = sorted((ROOT / "evals" / "results").glob("run_*.json"))
    if not runs:
        print("no runs yet: make eval")
        return 1
    out = json.loads(runs[-1].read_text())
    out["repo"] = {**(out.get("repo") or {}), **{k.removeprefix("repo."): v for k, v in code_counts().items()}}
    s = report.summarize(out)
    (ROOT / "evals" / "results" / "latest.json").write_text(json.dumps({"run": runs[-1].name, **s}, indent=2) + "\n")
    (ROOT / "evals" / "RESULTS.md").write_text(report.markdown(out, s, runs[-1].name))
    (ROOT / "docs" / "NAIVE_VS_FAULTLINE.md").write_text(report.naive_vs_markdown(out, runs[-1].name, s))
    print(f"regenerated from {runs[-1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
