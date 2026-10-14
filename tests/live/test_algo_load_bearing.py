"""Live: every algo.* tool is load-bearing. On a clean-room GRAPH.COPY, perturb the graph the algorithm reads and
assert that the DECISION built on it changes (README
"Graph is load-bearing"). If an algorithm's answer could change without the decision changing, it would be
decoration."""

import pytest

from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph import writes
from faultline.ingest.clock import ANCHOR_MS
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live
NOW = ANCHOR_MS + 3 * 3_600_000


@pytest.fixture
def room():
    db = gclient.engine()
    name = "eval_acme_loadbearing"
    gcopy.delete_if_exists(db, name)
    gcopy.copy_graph(db, "golden_acme", name)
    g = db.select_graph(name)

    def call(tool, **args):
        tok = context.bind("acme", graph=name, record=False)
        try:
            out = T.TOOLS[tool](**args)
        finally:
            context.unbind(tok)
        assert "error" not in out, out
        return out

    yield g, call
    gcopy.delete_if_exists(db, name)


def _cut_payment_to_checkout(g):
    g.query("MATCH (:Node {id:'payment'})-[p:PROPAGATES_TO]->(:Node {id:'checkout'}) DELETE p")


def test_bfs_blast_radius_sets_the_impact(room):
    g, call = room
    before = {r["id"] for r in call("blast_radius", id="payment")["rows"]}
    _cut_payment_to_checkout(g)
    after = {r["id"] for r in call("blast_radius", id="payment")["rows"]}
    assert "checkout" in before and "checkout" not in after


def test_sppaths_decides_g2(room):
    g, call = room
    assert call("causal_paths", from_id="payment", to_id="checkout")["rows"]
    _cut_payment_to_checkout(g)
    assert not call("causal_paths", from_id="payment", to_id="checkout")["rows"]  # → G2 "no path, no claim"


def test_maxflow_decides_g5(room):
    g, call = room
    assert call("impact_bound", suspect_ids=["payment"], symptom_id="checkout", observed_share=0.3)["verdict"] == "sufficient"
    g.query("MATCH (:Node {id:'payment'})-[p:PROPAGATES_TO]->(:Node {id:'checkout'}) SET p.cap = 0.01")
    assert call("impact_bound", suspect_ids=["payment"], symptom_id="checkout", observed_share=0.3)["verdict"] == "insufficient"


def test_maxflow_mincut_sets_the_cut(room):
    g, call = room
    protect = ["frontend-proxy"]
    before = {(r["u"], r["v"]) for r in call("containment_cut", failing_id="payment", protect_ids=protect)["rows"]}
    g.query("MATCH (:Node {id:'checkout'})-[p:PROPAGATES_TO]->(:Node {id:'frontend'}) SET p.cut_cost = 0.001")
    after = {(r["u"], r["v"]) for r in call("containment_cut", failing_id="payment", protect_ids=protect)["rows"]}
    assert before == {('payment', 'checkout')} and after == {('checkout', 'frontend')}


def test_wcc_decides_whether_to_cut(room):
    """post_gate cuts only if the failing component and the protected entry share a WCC component."""
    g, call = room

    def linked():
        return call("connectivity_check", target_id="payment", protect_ids=["frontend-proxy"])["linked"]

    assert linked()
    g.query("MATCH (:Node {id:'payment'})-[p:PROPAGATES_TO]-() DELETE p")
    assert not linked()


def test_sspaths_decides_no_incident(room):
    g, call = room
    writes.inject_change(g, id="D-lb-1", target="payment", at=NOW - 5 * 60_000, title="probe", tenant="acme")
    assert call("reachable_from_changes", now=NOW, window_min=30, anomalous_ids=["checkout"])["verdict"] == "reachable"
    _cut_payment_to_checkout(g)
    out = call("reachable_from_changes", now=NOW, window_min=30, anomalous_ids=["checkout"])
    assert out["verdict"] == "none_reachable"  # → negative proof accepted (NO_INCIDENT) instead of refused


def test_betweenness_orders_chokepoints(room):
    g, call = room
    top = call("chokepoints")["rows"][0]["id"]
    g.query("MATCH (s:Node {id:$id})-[c:CALLS]-() DELETE c", {"id": top})
    assert call("chokepoints")["rows"][0]["id"] != top


def test_pagerank_orders_investigation(room):
    g, call = room
    ids = ["payment", "email", "checkout", "frontend", "recommendation", "cart"]
    first = [r["id"] for r in call("rank_causes", incident_id="lb", node_ids=ids)["rows"]]
    g.query("UNWIND ['payment','checkout','frontend','recommendation','cart'] AS x MATCH (a:Node {id:x}), (e:Node {id:'email'}) "
            "MERGE (a)-[:DEPENDS_ON]->(e)")
    second = [r["id"] for r in call("rank_causes", incident_id="lb", node_ids=ids)["rows"]]
    assert second[0] == "email" and first != second


def test_harmonic_decides_who_is_paged(room):
    g, call = room
    since = NOW - 30 * 86_400_000
    first = [r["person"] for r in call("who_fixes", target_id="payment", now=NOW, since=since)["rows"]]
    g.query("MATCH (p:Person {id:$p})-[a:AUTHORED]->() DELETE a", {"p": first[0]})
    g.query("MATCH (p:Person {id:$p})-[r:RESOLVED]->() DELETE r", {"p": first[0]})
    second = [r["person"] for r in call("who_fixes", target_id="payment", now=NOW, since=since)["rows"]]
    assert second[0] != first[0]


def test_msf_decides_the_escalation_tree(room):
    g, call = room
    since = NOW - 30 * 86_400_000
    top = [r["person"] for r in call("who_fixes", target_id="payment", now=NOW, since=since)["rows"][:3]]
    tree = call("escalation_tree", person_ids=top)["rows"]
    e = tree[0]
    g.query("MATCH (a:Person {id:$a})-[c:COLLABORATES]-(b:Person {id:$b}) DELETE c", {"a": e["from"], "b": e["to"]})
    assert call("escalation_tree", person_ids=top)["rows"] != tree


def test_label_propagation_decides_the_derived_runbook(room):
    """Split the payment family apart → no family → no consolidated runbook for it."""
    from faultline.graph.ro import RO
    from faultline.memory.learn import consolidate_all, runbook_id

    g, _ = room
    g.query("MATCH (r:Runbook {source:'derived'}) DETACH DELETE r")
    rid = runbook_id("flip_flag", "paymentGate")
    assert rid in {x["runbook"] for x in consolidate_all("acme", g.name)}
    fam = next(f for f in RO("acme", g.name).run("Q-MEM-6", {"inc": "inc-h005"}).rows if f["mine"])["incidents"]
    g.query("MATCH (r:Runbook {source:'derived'}) DETACH DELETE r")
    g.query("UNWIND $ids AS i MATCH (n:Incident {id:i})-[h:HAS_SYMPTOM]->() DELETE h", {"ids": fam})
    g.query("UNWIND $ids AS i MATCH ()-[c:CAUSED]->(n:Incident {id:i}) DELETE c", {"ids": fam})
    assert rid not in {x["runbook"] for x in consolidate_all("acme", g.name)}


def test_family_pages_cover_exactly_the_families_q_mem_6_reads(room):
    """Q-MEM-6P (keyset pages for seed-time consolidation) returns the same families as Q-MEM-6, with no overlap."""
    from faultline.graph.ro import RO

    g, _ = room
    ro = RO("acme", g.name)
    one = {tuple(sorted(f["incidents"])) for f in ro.run("Q-MEM-6", {"inc": ""}).rows}
    page = ro.run("Q-MEM-6P", {"after": -1})
    assert not page.truncated and {tuple(sorted(f["incidents"])) for f in page.rows} == one
    ids = [f["communityId"] for f in page.rows]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    rest = ro.run("Q-MEM-6P", {"after": ids[0]}).rows  # the key moves past the first family only
    assert [f["communityId"] for f in rest] == ids[1:]


def test_consolidation_reads_every_page_before_writing(monkeypatch):
    """More families than one page: every page is read, in key order, before the first consolidation write."""
    from types import SimpleNamespace

    from faultline.memory import learn

    calls: list = []
    pages = {-1: [{"communityId": 1, "incidents": ["a", "b"], "size": 2}, {"communityId": 5, "incidents": ["c", "d", "e"], "size": 3}],
             5: [{"communityId": 9, "incidents": ["f", "g"], "size": 2}]}

    class FakeRO:
        def __init__(self, *_a):
            pass

        def run(self, tid, params):
            calls.append(("read", params["after"]))
            return SimpleNamespace(rows=pages[params["after"]], truncated=params["after"] == -1)

    monkeypatch.setattr(learn, "RO", FakeRO)
    monkeypatch.setattr(learn.client, "engine", lambda: SimpleNamespace(select_graph=lambda n: None))
    monkeypatch.setattr(learn, "_consolidate", lambda g, ro, t, members, k: calls.append(("write", members[0])) or None)
    learn.consolidate_all("acme", "golden_acme")
    assert calls == [("read", -1), ("read", 5), ("write", "c"), ("write", "a"), ("write", "f")]
    pages[5] = [{"communityId": 9, "incidents": ["a", "z"], "size": 2}]  # the projection moved between pages
    with pytest.raises(RuntimeError, match="overlap"):
        learn.consolidate_all("acme", "golden_acme")
