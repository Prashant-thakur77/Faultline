"""Unit: the text2cypher guard (no database)."""

import pytest

from faultline.graph.guard import GuardError, check_plan, guard

BAD = [
    "CREATE (n:Service {id:'x'}) RETURN n",
    "MATCH (n) MERGE (m:X {id:n.id}) RETURN m",
    "MATCH (n:Service) SET n.tier = 1 RETURN n",
    "MATCH (n) DELETE n",
    "MATCH (n) DETACH DELETE n",
    "MATCH (n) REMOVE n.tier RETURN n",
    "MATCH (n) FOREACH (x IN [1] | SET n.a = x) RETURN n",
    "LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row",
    "MATCH (n) RETURN n.id UNION MATCH (m) RETURN m.id",
    "GRAPH.QUERY tenant_globex 'MATCH (n) RETURN n'",
    "MATCH (n) RETURN n // sneaky",
    "MATCH (n) RETURN n /* sneaky */",
    "MATCH (n) RETURN n; MATCH (m) DELETE m",
    "CALL db.labels() YIELD label RETURN label",
    "CALL dbms.procedures() YIELD name RETURN name",
    "MATCH p=(a)-[*]->(b) RETURN p",
    "MATCH p=(a)-[*2..]->(b) RETURN p",
    "MATCH p=(a)-[*1..20]->(b) RETURN p",
    "MATCH (n) RETURN n LIMIT 1000",
    "MATCH (n) RETURN n LIMIT $k",
    "drop index on :Service(id)",
]


@pytest.mark.parametrize("q", BAD)
def test_rejected(q):
    with pytest.raises(GuardError):
        guard(q)


def test_limit_appended_and_kept():
    assert guard("MATCH (n:Service) RETURN n.id AS id ORDER BY id").endswith("LIMIT 100")
    assert guard("MATCH (n:Service) RETURN n.id LIMIT 5;") == "MATCH (n:Service) RETURN n.id LIMIT 5"


def test_keywords_inside_strings_do_not_trip_or_hide():
    assert guard("MATCH (n:Decision) WHERE n.title CONTAINS 'CREATE INDEX; DELETE' RETURN n.id")
    with pytest.raises(GuardError):  # a real write after a string is still caught
        guard("MATCH (n {title:'x'}) SET n.title = 'y' RETURN n")


def test_allowlisted_procedures_pass():
    assert guard("CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node RETURN node.id")


def test_cartesian_over_full_scans_rejected():
    plan = ["Results", "    Project", "        Cartesian Product", "            All Node Scan | (a)", "            All Node Scan | (b)"]
    with pytest.raises(GuardError):
        check_plan(plan)
    check_plan(["Results", "    Project", "        Node By Index Scan | (a:Service)"])


@pytest.mark.parametrize("q", ["MATCH (a)-[r:PROPAGATES_TO* {k: ''}]->(b) RETURN b LIMIT 5",
                               "MATCH (a)-[*1..99 {k:''}]->(b) RETURN b LIMIT 5"])
def test_varlen_with_a_property_map_cannot_slip_past_the_bound(q):
    """Review round 4 (M6): a property map after the range used to skip the upper-bound check."""
    from faultline.graph.guard import GuardError, guard

    with pytest.raises(GuardError, match="variable-length"):
        guard(q)


def test_plan_check_rejects_an_unbounded_traversal():
    from faultline.graph.guard import GuardError, check_plan

    with pytest.raises(GuardError, match="unbounded"):
        check_plan(["Results", "    Conditional Variable Length Traverse | (a)-[@anon_0*1..INF]->(b)"])
