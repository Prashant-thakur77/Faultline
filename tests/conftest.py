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
