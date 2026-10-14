"""Live: who_fixes and escalation_tree with their grouping and ranking inputs computed in Cypher (M14 #6).
Before, who_fixes read its commits and collaborators with LIMIT 100 and never checked truncation: on busy components
the projection was silently partial (43 of 442 who_fixes calls across both tenants differed, every one a truncated
read). Now the pairs are keyset-paged (Q-ORG-KNOWS) and every person's reasons come from Q-ORG-WHO."""

import pytest

from faultline.graph import client
from faultline.graph.ro import RO
from faultline.ingest.clock import ANCHOR_MS
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
YEAR = 365 * 86_400_000


@pytest.fixture
def bound():
    toks = []

    def bind(tenant):
        toks.append(context.bind(tenant, run_id=None, graph=f"golden_{tenant}", record=False))
    yield bind
    for t in reversed(toks):
        context.unbind(t)


def test_every_recent_commit_is_counted_on_a_busy_component(bound):
    """acme payment over a year: more commit rows than one LIMIT-100 read; each author's count is complete."""
    bound("acme")
    w = T.who_fixes(target_id="payment", now=ANCHOR_MS, since=ANCHOR_MS - YEAR)
    assert "error" not in w
    direct = client.engine().select_graph("golden_acme").ro_query(
        "MATCH (:Node {id:'payment'})<-[:PART_OF]-(:File)<-[:TOUCHES]-(cm:Commit)<-[:AUTHORED]-(a:Person) "
        "WHERE cm.at >= $s AND a.active RETURN a.id, count(DISTINCT cm)", {"s": ANCHOR_MS - YEAR}).result_set
    want = {p: n for p, n in direct}
    for x in w["rows"]:
        line = next((r for r in x["reasons"] if r.startswith("authored ")), None)
        assert (int(line.split()[1]) if line else 0) == want.get(x["person"], 0), x
    assert any(r == "authored 22 recent commit(s) on payment" for x in w["rows"] for r in x["reasons"])


def test_pairs_are_paged_disjoint_and_complete_on_the_busiest_component(bound):
    bound("globex")
    ro = RO("globex", "golden_globex")
    p = {"target": "storefront-bff", "now": ANCHOR_MS, "since": ANCHOR_MS - YEAR, "min_collab": T.MIN_COLLAB}
    keys, after, pages = [], ("", ""), 0
    while True:
        r = ro.run("Q-ORG-KNOWS", p | {"after_a": after[0], "after_b": after[1]})
        pages += 1
        keys += [(x["a"], x["b"]) for x in r.rows]
        if not r.truncated:
            break
        after = keys[-1]
    assert pages >= 3 and keys == sorted(keys) and len(set(keys)) == len(keys)
    w = T.who_fixes(target_id="storefront-bff", now=ANCHOR_MS, since=ANCHOR_MS - YEAR)
    assert w["template"].split("+").count("Q-ORG-KNOWS") == pages   # who_fixes read every page into the projection


def test_escalation_weights_are_the_strongest_tie_per_pair(bound):
    bound("acme")
    ids = ["p-004", "p-017", "p-030", "p-036"]
    rows = RO("acme", "golden_acme").run("Q-ORG-COLLAB-W", {"ids": ids}).rows
    raw = client.engine().select_graph("golden_acme").ro_query(
        "MATCH (a:Person)-[r:COLLABORATES|REPORTS_TO]->(b:Person) WHERE a.id IN $ids AND b.id IN $ids "
        "RETURN a.id, b.id, type(r), coalesce(r.w, 1.0)", {"ids": ids}).result_set
    want: dict = {}
    for a, b, rel, w in raw:
        k = tuple(sorted((a, b)))
        want[k] = max(want.get(k, 0.0), float(w) if rel == "COLLABORATES" else 0.5)
    assert {(x["a"], x["b"]): x["w"] for x in rows} == want and want
    tree = T.escalation_tree(person_ids=ids)["rows"]
    assert [x["w"] for x in tree] == sorted((x["w"] for x in tree), reverse=True)   # strongest tie first (Q-ORG-MSF)
