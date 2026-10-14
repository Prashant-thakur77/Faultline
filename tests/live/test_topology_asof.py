"""Live, M14 #7: the as-of topology. A PR merged before a call existed does not see that call in its blast radius
read as of its merge (Q-PRE-1-ASOF), and as-of reach is always a subset of today's reach (Q-PRE-1)."""

import pytest

from faultline.graph import client
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.mark.parametrize("tenant", ["globex", "acme"])
def test_as_of_reach_never_exceeds_now_and_misses_later_calls(tenant):
    g = client.engine().select_graph(f"golden_{tenant}")
    ro = RO(tenant, f"golden_{tenant}")
    dated = g.ro_query("MATCH (a)-[r:PROPAGATES_TO]->(b) WHERE r.valid_from IS NOT NULL "
                       "RETURN a.id, b.id, r.valid_from ORDER BY r.valid_from").result_set
    assert dated, "the seed dates some calls (ingest/topology_history.py)"
    prs = g.ro_query("MATCH (p:PR) RETURN p.id, p.merged_at ORDER BY p.merged_at, p.id").result_set
    smaller = 0
    for pr, at in prs[::3]:
        now = {(r["changed"], r["impacted"]) for r in ro.run("Q-PRE-1", {"pr": pr}).rows}
        then = ro.run("Q-PRE-1-ASOF", {"pr": pr, "as_of": int(at)})
        assert not then.truncated
        then = {(r["changed"], r["impacted"]) for r in then.rows}
        assert then <= now, pr
        smaller += then < now
    assert smaller > 0   # some past PR really had a smaller blast radius than the topology of today would claim


def test_topology_at_names_the_call_and_the_pr_that_added_it():
    from faultline.mcp_server import context
    from faultline.mcp_server import tools as T

    g = client.engine().select_graph("golden_globex")
    a, b, at, pr = g.ro_query("MATCH (a)-[r:PROPAGATES_TO]->(b) WHERE r.valid_from IS NOT NULL "
                              "RETURN a.id, b.id, r.valid_from, r.introduced_by ORDER BY r.valid_from, a.id LIMIT 1").result_set[0]
    tok = context.bind("globex", run_id=None, graph="golden_globex", record=False)
    try:
        before = T.topology_at(target_id=a, at=int(at) - 1)
        after = T.topology_at(target_id=a, at=int(at))
    finally:
        context.unbind(tok)
    assert {"from": a, "to": b, "at": at, "pr": pr} in before["calls_since"]          # named, with its PR
    assert not any(c["from"] == a and c["to"] == b for c in after["calls_since"])     # once merged, it is there
    assert before["then"] <= after["then"] <= after["now"]
    assert pr.startswith("gx-pr-") and "introduces" not in before.get("error", "")
