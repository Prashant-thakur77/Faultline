import os
import uuid

import pytest
from falkordb import FalkorDB


@pytest.fixture(scope="session")
def db():
    try:
        d = FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379")))
        d.list_graphs()
    except Exception as e:  # live tests need `make up`
        pytest.skip(f"FalkorDB not reachable: {e}")
    return d


@pytest.fixture
def scratch(db):
    name = f"smoke_live_{uuid.uuid4().hex[:8]}"
    g = db.select_graph(name)
    yield g
    try:
        g.delete()
    except Exception:
        pass


# M20 #6: change-freeze windows are evaluated on the wall clock (the engine clock in the product). Every test runs at a
# fixed Wednesday 12:00 UTC (outside the seeded payment weekend freeze), so a suite run on a weekend gives the same
# preflight verdicts; tests of the freeze itself pass their own instants (tests/preflight/test_freeze.py).
FREEZE_TEST_AT = 1791979200000   # 2026-10-14T12:00:00Z, a Wednesday


@pytest.fixture(autouse=True)
def _pin_freeze_clock(monkeypatch):
    from faultline.preflight import score

    monkeypatch.setattr(score, "FREEZE_AT", FREEZE_TEST_AT)
    yield

