"""Schema drift check: the live graphs vs `backend/faultline/graph/schema_model.py` (fails loudly).

Fails (exit 1) when
  * a graph holds a label or relationship type that schema_model does not declare (even with 0 nodes/edges: the
    engine registered it, so something wrote it or indexed it);
  * a declared relationship type is absent from every checked graph and is not listed in RUNTIME_RELS (created
    only by runs/actions/scratch projections) or RESERVED_RELS (declared on purpose, no writer yet);
  * a template reads a relationship type that schema_model does not declare.
Reports (no failure): write-only relationship types (present in a graph, read by no template), reserved types that
now appear, and declared labels with no nodes. Every read is a template through GRAPH.RO_QUERY (Q-SCHEMA-1..4).

    PYTHONPATH=backend uv run python scripts/check_schema_drift.py                 # every tenant_<t> graph
    PYTHONPATH=backend uv run python scripts/check_schema_drift.py --golden        # golden_<t> (seeded state)
    PYTHONPATH=backend uv run python scripts/check_schema_drift.py --tenant acme --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from faultline.graph.errors import GraphError  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.schema_introspect import drift, introspect, tenants_in_engine  # noqa: E402
from faultline.graph.tenant import golden_graph, tenant_graph  # noqa: E402


def live_schemas(tenants: list[str], golden: bool) -> dict[str, dict]:
    out = {}
    for t in tenants:
        name = golden_graph(t) if golden else tenant_graph(t)
        out[name] = introspect(RO(t, name))[0]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", action="append", help="tenant to check (repeatable; default: every tenant_<t> graph)")
    ap.add_argument("--golden", action="store_true", help="check golden_<t> (the seeded state) instead of tenant_<t>")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args(argv)
    try:
        tenants = a.tenant or tenants_in_engine()
        if not tenants:
            print("schema drift: no tenant graphs found (run `make seed`)", file=sys.stderr)
            return 2
        rep = drift(live_schemas(tenants, a.golden))
    except GraphError as e:
        print(f"schema drift: FalkorDB error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, indent=1, sort_keys=True))
    else:
        print(f"graphs checked: {', '.join(rep['graphs'])}")
        print(f"write-only relationship types (present, read by no template): {', '.join(rep['write_only']) or 'none'}")
        print(f"runtime-only types not present now: {', '.join(rep['runtime_absent']) or 'none'}")
        print(f"reserved types (declared, no writer): {', '.join(rep['reserved_absent']) or 'none'}")
        if rep["reserved_present"]:
            print(f"NOTE reserved types now present (move them out of RESERVED_RELS): {', '.join(rep['reserved_present'])}")
        print(f"declared labels with no nodes: {', '.join(rep['labels_absent']) or 'none'}")
        for f in rep["failures"]:
            print(f"FAIL {f}")
        print("schema drift check " + ("PASS" if rep["ok"] else "FAILED"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
