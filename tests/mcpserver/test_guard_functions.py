"""M20 #7: guarded text2cypher may call only the functions the ENGINE reports as built-ins (dbms.functions(), template
Q-FUNCS) plus the vetted UDFs; every other loaded UDF and every unknown name is refused. Unit tests use a recorded
catalogue; the live test reads the pinned engine's own catalogue through the read-only wrapper."""

import pytest

from faultline.graph import guard as G

CATALOGUE = {"builtin": ["toLower", "tostring", "count", "percentileCont", "stDevP", "avg", "coalesce", "size",
                         "labels", "vec.cosineDistance", "list.dedup"],
             "udfs": ["flex.text.jaroWinkler", "flex.sim.jaccard", "flex.text.repeat", "flex.coll.shuffle"]}


@pytest.fixture
def allowed():
    G.reset_functions_cache()
    yield G.allowed_functions(lambda: CATALOGUE)
    G.reset_functions_cache()


def check(q: str, allowed) -> None:
    G.check_functions(G.guard(q), allowed)


def test_unvetted_udf_is_refused(allowed):
    with pytest.raises(G.GuardError, match="flex.text.repeat"):
        check("RETURN flex.text.repeat('x', 100000000) AS s", allowed)
    with pytest.raises(G.GuardError, match="flex.coll.shuffle"):
        check("MATCH (s:Service) RETURN flex.coll.shuffle(collect(s.id)) AS ids", allowed)
    with pytest.raises(G.GuardError):        # backticks or spaces around the dots do not hide it
        check("RETURN `flex.text.repeat`('x', 10) AS s", allowed)
    with pytest.raises(G.GuardError):
        check("RETURN flex . text . repeat('x', 10) AS s", allowed)


def test_vetted_udf_and_builtins_pass(allowed):
    check("MATCH (s:Service) RETURN s.id, flex.text.jaroWinkler(toLower(s.name), 'payment') AS sim ORDER BY sim DESC", allowed)
    check("MATCH (w:MetricWindow) RETURN percentileCont(w.value, 0.95) AS p95, stDevP(w.value) AS sd, avg(w.value) AS mu",
          allowed)
    check("MATCH (n:Service) WHERE all(x IN labels(n) WHERE size(x) > 0) RETURN count(*) AS n", allowed)
    check("MATCH (n:Service) RETURN TOLOWER(n.name) AS x, toString(n.tier) AS t", allowed)   # built-ins: any case


def test_unknown_function_is_refused(allowed):
    with pytest.raises(G.GuardError, match="apoc.text.join"):
        check("MATCH (n:Service) RETURN apoc.text.join(collect(n.id), ',') AS x", allowed)
    with pytest.raises(G.GuardError, match="datetime"):          # not in 6.0.2's catalogue
        check("RETURN datetime() AS now", allowed)


def test_names_inside_strings_keywords_and_procedures_are_not_calls(allowed):
    check("MATCH (n:Service) WHERE n.name = 'flex.text.repeat(x)' RETURN n.id", allowed)
    check("CALL db.idx.fulltext.queryNodes('Service', 'pay*') YIELD node RETURN node.id", allowed)
    check("MATCH (a:Service)-[:CALLS]->(b:Service) WHERE NOT (a)-[:CALLS]->(a) AND (b.tier = 1 OR (b.tier = 2)) "
          "RETURN DISTINCT(a.id) AS a, CASE WHEN (b.tier > 1) THEN 'x' ELSE 'y' END AS t", allowed)


def test_only_vetted_udfs_the_engine_actually_loaded_are_allowed():
    G.reset_functions_cache()
    try:
        allowed = G.allowed_functions(lambda: {"builtin": ["count"], "udfs": []})   # FLEX not loaded
        with pytest.raises(G.GuardError):
            G.check_functions("RETURN flex.sim.jaccard([1], [1]) AS j", allowed)
    finally:
        G.reset_functions_cache()


def test_an_empty_catalogue_fails_closed():
    G.reset_functions_cache()
    try:
        with pytest.raises(G.GuardError, match="no built-in functions"):
            G.allowed_functions(lambda: {"builtin": [], "udfs": []})
    finally:
        G.reset_functions_cache()


@pytest.mark.live
def test_live_catalogue_from_the_pinned_engine(db):
    from faultline.graph.ro import RO

    G.reset_functions_cache()
    try:
        ro = RO("acme")
        row = ro.run("Q-FUNCS", {}).rows[0]
        allowed = G.allowed_functions(lambda: row)
        assert row["total"] >= 150 and "flex.text.repeat" in row["udfs"]
        assert "percentilecont" in allowed and "flex.text.jarowinkler" in allowed
        assert "flex.text.repeat" not in allowed
        with pytest.raises(G.GuardError):
            ro.run_guarded("RETURN flex.text.repeat('x', 100000000) AS s")
        assert ro.run_guarded("MATCH (s:Service) RETURN toLower(s.id) AS id ORDER BY id LIMIT 3").rows
    finally:
        G.reset_functions_cache()
