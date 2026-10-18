"""Live: our own FalkorDB UDF library (deploy/udf/faultline-1.0.0.js) ranks inside the engine.

blast_radius (Q-BLAST-3), notify_set (Q-NOTIFY-2) and find_entities (Q-FIND-HYBRID) used to fetch graph facts and then
score, sum, merge and sort them in Python. Each is now one read-only query whose rows come back scored and ordered by
FalkorDB. These tests hold the engine to the documented formulas: the reference implementations below are the old
Python code, kept here as the test oracle only.
"""

import math
import random

import pytest

from faultline.agent.weights import tier_weight, tier_weights_param, weights
from faultline.graph import client, udf
from faultline.graph.ro import RO
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def acme(db):
    udf.load_udfs(db.connection)                       # idempotent (REPLACE); what make up / seed / API start do
    tok = context.bind("acme")
    yield RO("acme")
    context.unbind(tok)


def test_library_is_loaded_at_its_pinned_sha(db):
    udf.load_udfs(db.connection)
    st = udf.udf_status(db.connection)
    assert st["faultline"]["state"] == "loaded" and st["flex"]["state"] == "loaded"


def test_round4_is_pythons_round(acme):
    rnd = random.Random(42)
    xs = ([k / 32 for k in range(-200, 201)]                    # every exact half at the 4th decimal (x = odd/32)
          + [rnd.uniform(0, 3) for _ in range(2000)] + [rnd.uniform(-1, 1) * 10 ** -rnd.randint(1, 6) for _ in range(500)]
          + [0.0, 2.675, 1.00005, 0.00015, 123.45675])
    got = [r[0] for r in client.engine().select_graph("tenant_acme").ro_query(
        "UNWIND $xs AS x RETURN faultline.round4(x)", {"xs": xs}).result_set]
    assert got == [round(x, 4) for x in xs]


def _impact_ref(tier, hops, traffic):
    return round(tier_weight(tier) * (1.0 / (1 + hops)) * math.log1p(max(traffic, 0.0) + 1.0), 4)


def test_impact_matches_the_documented_formula(acme):
    rnd = random.Random(7)
    cases = [(rnd.choice([1, 2, 3, None, 0, 7]), rnd.choice([None, 0, 1, 2, 3, 5, 8]), rnd.choice([None, 0.0, rnd.uniform(-5, 100)]))
             for _ in range(1500)]
    got = [r[0] for r in client.engine().select_graph("tenant_acme").ro_query(
        "UNWIND $cs AS c RETURN faultline.round4(faultline.impact($tw, c[0], c[1], c[2]))",
        {"cs": [list(c) for c in cases], "tw": tier_weights_param()}).result_set]
    assert got == [_impact_ref(t, int(h or 1), float(x or 0)) for t, h, x in cases]


def _ids(n: int) -> list[str]:
    rows = client.engine().select_graph("tenant_acme").ro_query(
        "MATCH (n:Node)-[:PROPAGATES_TO]->() RETURN DISTINCT n.id ORDER BY n.id").result_set
    return [r[0] for r in rows][:n]


def test_blast_radius_ranking_equals_the_reference(acme):
    for i in _ids(120):
        reach = acme.run("Q-BLAST-1", {"id": i})
        hops = {r["id"]: r for r in acme.run("Q-BLAST-2", {"id": i}).rows}
        ref = sorted(({**r, "hops": hops.get(r["id"], {}).get("hops"),
                       "impact": _impact_ref(r.get("tier"), int(hops.get(r["id"], {}).get("hops") or 1),
                                             float(hops.get(r["id"], {}).get("max_cap") or 0) * 100)} for r in reach.rows),
                     key=lambda x: (-x["impact"], x["id"]))
        got = T.blast_radius(id=i)
        assert got["template"] == "Q-BLAST-3"
        assert [(x["id"], x["hops"], x["impact"]) for x in got["rows"]] == [(x["id"], x["hops"], x["impact"]) for x in ref], i


def test_notify_set_sums_and_orders_in_the_engine(acme):
    rnd = random.Random(3)
    ids = _ids(80)
    for i in ids:
        pri = sorted(rnd.sample(ids, 3)) if rnd.random() < 0.4 else []
        blast = {r["id"]: r for r in acme.run("Q-BLAST-2", {"id": i}).rows if r["id"] != i}
        got = T.notify_set(target_id=i, now=0, priority_ids=pri)
        assert got["template"] == "Q-NOTIFY-2"
        for row in got["rows"]:
            mine = [n for n in row["owns_impacted"] if n in blast]
            assert mine == row["owns_impacted"]                      # every owned node is in the blast radius
            assert row["impact"] == round(sum(tier_weight(blast[n]["tier"]) * float(blast[n]["max_cap"] or 0)
                                              / (1 + int(blast[n]["hops"])) for n in mine), 4)
            assert row["nearest_hops"] == min(int(blast[n]["hops"]) for n in mine)
            assert ("priority" in row) == bool(pri)
        key = [(not r.get("priority"), -r["impact"], r["team"]) for r in got["rows"]]
        assert key == sorted(key)


def test_find_entities_is_one_query_with_engine_side_merge(acme):
    r = T.find_entities(text="kafka consumer lag")
    assert r["template"] == "Q-FIND-HYBRID" and r["cypher"].count("UNION ALL") == 5
    scores = [(-x["score"], x["id"]) for x in r["rows"]]
    assert scores == sorted(scores) and len({x["id"] for x in r["rows"]}) == len(r["rows"])
    floor = float(weights()["memory"]["find_min_similarity"])
    assert all(x["score"] >= floor for x in r["rows"] if x["via"] == ["vector"])
    d = T.find_entities(text="checkout", labels=["Decision"])
    assert all(x["label"] == "Decision" and "status" in x for x in d["rows"])
    assert T.find_entities(text="checkout", labels=["Nope"]) == {"error": "invalid arguments: no supported labels"}


def test_containment_cut_is_computed_in_the_engine_and_equals_the_reference(acme):
    """Q-CUT-3 computes the min-cut inside FalkorDB (residual reachability as a list fixpoint, in the same query as
    algo.maxFlow); graph/algo/maxflow.py::min_cut over Q-CUT-1 + Q-CUT-2 is the oracle."""
    from faultline.graph.algo.maxflow import min_cut

    for f in _ids(60):
        reach = [x["id"] for x in T.blast_radius(id=f)["rows"] if x["id"] != f]
        if not reach:
            continue
        prot = sorted(set(reach[:3]))
        got = T.containment_cut(failing_id=f, protect_ids=prot)
        assert got["template"] == "Q-CUT-3", got
        flow = acme.run("Q-CUT-1", {"failing": f, "protect": prot}).rows[0]
        cand = acme.run("Q-CUT-2", {"failing": f}).rows
        cap = {f"{e['u']}>{e['v']}": float(e["cut_cost"]) for e in cand}
        cut, side = min_cut({f}, [(e["u"], e["v"], f"{e['u']}>{e['v']}") for e in cand], cap,
                            {f"{u}>{v}": float(x) for (u, v), x in zip(flow["flow_edges"], flow["flows"])},
                            float(flow["max_flow"]), targets=set(prot))
        assert [(c["u"], c["v"], c["cut_cost"]) for c in got["rows"]] == [(u, v, cap[e]) for u, v, e in cut], f
        assert got["max_flow"] == float(flow["max_flow"]) and got["source_side"] == sorted(side), f
