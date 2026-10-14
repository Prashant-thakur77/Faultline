"""Live: Q-PROTECT-1 on a scratch graph whose failing component reaches 25 entry services: the read keeps 20, tier-1
first then the revenue path, and every row says how many are reachable in all and how many are tier 1."""

import uuid

import pytest

from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


def test_protect_set_ranks_tier1_then_revenue_and_counts_everything():
    db = gclient.engine()
    name = f"scratch_acme_protect_{uuid.uuid4().hex[:10]}"
    g = db.select_graph(name)
    try:
        g.query("CREATE (f:Node:Service {id: 'f'}) WITH f UNWIND range(1, 25) AS i "
                "CREATE (f)-[:PROPAGATES_TO {cap: 1.0}]->(:Node:Service {id: 'e' + toString(100 + i), entry: true, "
                "tier: CASE WHEN i % 6 = 0 THEN 1 ELSE 2 END, revenue_path: i % 5 = 0})")
        res = RO("acme", name).run("Q-PROTECT-1", {"target": "f"})
        rows = res.rows
        assert res.truncated and len(rows) == 20
        assert {int(r["total"]) for r in rows} == {25} and {int(r["tier1"]) for r in rows} == {4}
        assert [r["id"] for r in rows[:4]] == ["e106", "e112", "e118", "e124"]          # every tier-1 entry first
        assert [r["id"] for r in rows[4:8]] == ["e105", "e110", "e115", "e120"]         # then tier-2 on the revenue path
    finally:
        gcopy.delete_if_exists(db, name)
