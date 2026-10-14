"""Garbage-collect leftover eval/whatif/scratch graphs for a tenant (`make gc`).

Keeps graphs that the most recent runs in the audit index (`RunIndex`) still point at, so the UI's
incident list keeps working. Golden, tenant and audit graphs are never touched.

    PYTHONPATH=backend uv run python scripts/gc_graphs.py --tenant acme [--keep-recent 20] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from faultline.graph import client  # noqa: E402
from faultline.graph.copy import gc_eval_graphs  # noqa: E402
from faultline.graph.errors import GraphNotReady  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.tenant import audit_graph  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--keep-recent", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        rows = RO(a.tenant, audit_graph(a.tenant)).run("Q-RUNS-1", {}).rows
    except GraphNotReady:
        rows = []
    keep = {r["graph"] for r in rows[: a.keep_recent] if r.get("graph")}
    doomed = gc_eval_graphs(client.engine(), a.tenant, keep, dry_run=a.dry_run)
    print(f"{'would drop' if a.dry_run else 'dropped'} {len(doomed)} graphs; kept {len(keep)} referenced by recent runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
