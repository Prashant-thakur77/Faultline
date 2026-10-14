"""`make smoke`: every critical engine item must pass on the pinned engine (needs FalkorDB)."""

import os

import pytest

from faultline.graph.smoke.runner import Smoke

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def results():
    s = Smoke(os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379")),
              os.getenv("FALKORDB_ENGINE_USER") or None, os.getenv("FALKORDB_ENGINE_PASSWORD") or None)
    return s.run_all()


def test_record_pinned_run(results):
    """`make smoke` keeps a record of the run against the pinned engine (docs/audit/smoke_pinned.json)."""
    import json
    import time
    from pathlib import Path

    out = Path(__file__).resolve().parents[4] / "docs" / "audit" / "smoke_pinned.json"
    out.write_text(json.dumps({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results}, indent=2, default=str))


def test_all_critical_items_pass(results):
    failed = [f"{r['id']} {r['item']}: {r['notes'][:160]}" for r in results if r["critical"] and not r["ok"]]
    assert not failed, "critical smoke items failed:\n" + "\n".join(failed)
