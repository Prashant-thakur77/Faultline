"""Live (M20 #1): FalkorDB itself refuses records that break the evidence contract.

Every MANDATORY property of graph/constraints.py is refused when missing, UNIQUE ids are refused when repeated, a batch
with one bad row rolls back whole, a GRAPH.COPY clean room carries the golden graph's constraints, the product's own
writers pass them, and the perturbation: with the Evidence constraint dropped a provenance-less write lands, and putting
the constraint back over that data fails loudly (naming the violator) instead of silently accepting it.
"""

import uuid

import pytest

from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.graph.constraints import CONSTRAINTS, STATUS_QUERY, key_of

pytestmark = pytest.mark.live

MANDATORY_NODE = [c for c in CONSTRAINTS if c.kind == "MANDATORY" and c.entity == "NODE" and c.label != "Node"]
MANDATORY_REL = [c for c in CONSTRAINTS if c.kind == "MANDATORY" and c.entity == "RELATIONSHIP"]


@pytest.fixture
def cg(scratch):
    writes.apply_schema(scratch)
    return scratch


def _status(g) -> dict:
    return {key_of(r): r[4] for r in g.ro_query(STATUS_QUERY).result_set}


def test_apply_schema_makes_every_constraint_operational(cg):
    st = _status(cg)
    assert {c.key for c in CONSTRAINTS} <= set(st)
    assert all(st[c.key] == "OPERATIONAL" for c in CONSTRAINTS), st
    again = writes.ensure_constraints(cg)                       # idempotent: nothing left to create
    assert again == {"total": len(CONSTRAINTS), "created": 0, "operational": len(CONSTRAINTS)}


@pytest.mark.parametrize("c", MANDATORY_NODE, ids=lambda c: c.label)
def test_missing_mandatory_node_property_is_refused(cg, c):
    for p in c.props:
        props = {x: f"v-{x}" for x in c.props if x != p}
        props.setdefault("id", f"{c.label.lower()}-{p}") if p != "id" else None
        with pytest.raises(Exception, match=rf"mandatory constraint violation.*{c.label}.*{p}"):
            cg.query(f"CREATE (x:{c.label}) SET x = $p", {"p": props})
    full = {x: f"v-{x}" for x in c.props}
    cg.query(f"CREATE (x:{c.label}) SET x = $p", {"p": full})        # all present: accepted


@pytest.mark.parametrize("c", MANDATORY_REL, ids=lambda c: c.label)
def test_missing_mandatory_edge_property_is_refused(cg, c):
    cg.query("CREATE (:Node {id:'ea'}), (:Node {id:'eb'})")
    for p in c.props:
        props = {x: 1 for x in c.props if x != p}
        with pytest.raises(Exception, match=rf"mandatory constraint violation.*{c.label}.*{p}"):
            cg.query(f"MATCH (a:Node {{id:'ea'}}), (b:Node {{id:'eb'}}) CREATE (a)-[r:{c.label}]->(b) SET r = $p",
                     {"p": props})
    cg.query(f"MATCH (a:Node {{id:'ea'}}), (b:Node {{id:'eb'}}) CREATE (a)-[r:{c.label}]->(b) SET r = $p",
             {"p": {x: 1 for x in c.props}})


def test_unique_ids_are_refused_and_the_label_less_run_bug_is_loud(cg):
    with pytest.raises(Exception, match="mandatory constraint violation.*Node.*id"):
        cg.query("CREATE (:Node {name:'no id'})")
    # the latent bug (docs/plans/M20 #1): a label-less Run, then a Run:Node writer with the same id. Before M20 the
    # second MERGE silently created a second Run; now FalkorDB refuses it. The product's writers all use Run:Node.
    cg.query("MERGE (r:Run {id:'run-x'}) RETURN r.id")
    with pytest.raises(Exception, match="unique constraint violation"):
        cg.query("MERGE (r:Run:Node {id:'run-x'}) RETURN r.id")
    cg.query("CREATE (:Intent {idem:'k', state:'PENDING'})")
    with pytest.raises(Exception, match="unique constraint violation"):
        cg.query("CREATE (:Intent {idem:'k', state:'PENDING'})")


def test_a_retired_constraint_is_dropped_where_it_still_exists(cg):
    """UNIQUE (Node) id was created by the first M20 build; 6.0.2 makes it cost O(label size) per insert, so
    ensure_constraints drops it wherever it is left (graph/constraints.py RETIRED)."""
    from faultline.graph.constraints import RETIRED

    r = RETIRED[0]
    cg.execute_command("GRAPH.CONSTRAINT", "CREATE", cg.name, *r.args())
    writes.ensure_constraints(cg)
    assert r.key not in _status(cg)


def test_a_batch_with_one_bad_row_rolls_back_whole(cg):
    rows = [{"id": "ev-ok", "digest": "d1"}, {"id": "ev-bad", "digest": None}]
    with pytest.raises(Exception, match="mandatory constraint violation"):
        cg.query("UNWIND $rows AS r CREATE (e:Evidence:Node {id: r.id, kind: 'k', source: 's', digest: r.digest})",
                 {"rows": rows})
    assert cg.ro_query("MATCH (e:Evidence) RETURN count(e)").result_set[0][0] == 0


def test_product_writers_pass_the_constraints(cg):
    """The run writers, both evidence writers and the refused-call writer under the constraints (Run:Node, one Run)."""
    common = dict(tenant="acme", tool="t", template="Q-COUNT-1", cypher="MATCH (n) RETURN n", params={}, digest="d" * 64,
                  rows=0, ms=1.0, truncated=False, served_by="test", seen_ids=[], kind="probe", about=[])
    writes.record_tool_call(cg, run_id="run-c", tc_id="tc-1", ev_id="ev-1", **common)
    writes.record_external_evidence(cg, run="run-c", tc_id="tc-2", tool="t2", ev_id="ev-2", kind="metric",
                                    source="warehouse", transport="duckdb", params={}, payload={"a": 1}, digest="e" * 64,
                                    about=[], summary="", ms=1.0, rows=1)
    writes.record_refused_call(cg, run="run-c", tenant="acme", tc_id="tc-3", tool="t3", stage="TRIAGE", error="no")
    n = cg.ro_query("MATCH (r:Run {id:'run-c'}) RETURN count(r), min(size(labels(r)))").result_set[0]
    assert n == [1, 2]                                                  # one Run, labelled Run:Node
    assert cg.ro_query("MATCH (:Run {id:'run-c'})-[:HAS_TOOL_CALL]->(t) RETURN count(t)").result_set[0][0] == 3


def test_clean_room_copy_carries_the_constraints(db):
    src = "golden_acme"
    if src not in db.list_graphs():
        pytest.skip("golden_acme not seeded (make seed)")
    dst = f"eval_acme_constraints_{uuid.uuid4().hex[:6]}"
    try:
        gcopy.copy_graph(db, src, dst)
        want, got = _status(db.select_graph(src)), _status(db.select_graph(dst))
        assert got == want and all(v == "OPERATIONAL" for v in got.values())
        assert {c.key for c in CONSTRAINTS} <= set(got)
        with pytest.raises(Exception, match="mandatory constraint violation.*Evidence"):
            db.select_graph(dst).query("CREATE (:Evidence:Node {id:'forged', kind:'metric', source:'nowhere'})")
    finally:
        gcopy.delete_if_exists(db, dst)


def test_perturbation_drop_the_evidence_constraint_and_the_forgery_lands(cg):
    ev = next(c for c in CONSTRAINTS if c.label == "Evidence")
    forge = "CREATE (:Evidence:Node {id:'forged', kind:'metric', source:'nowhere'})"
    with pytest.raises(Exception, match="missing property digest"):
        cg.query(forge)
    cg.execute_command("GRAPH.CONSTRAINT", "DROP", cg.name, *ev.args())
    cg.query(forge)                                                     # without the engine rule: accepted silently
    with pytest.raises(writes.WriteError, match=r"violates MANDATORY \(Evidence\).*forged"):
        writes.ensure_constraints(cg)                                   # restoring over bad data fails loudly
    assert ev.key not in _status(cg)                                    # the FAILED constraint is not left behind
    cg.query("MATCH (e:Evidence {id:'forged'}) DELETE e")
    writes.ensure_constraints(cg)
    with pytest.raises(Exception, match="missing property digest"):
        cg.query(forge)
