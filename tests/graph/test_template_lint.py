import pytest

from faultline.graph.templates import TemplateLintError, catalogue, lint, parse


def _write(tmp_path, body, returns="rows"):
    p = tmp_path / "t.cypher"
    p.write_text(f"// id: T-1\n// returns: {returns}\n{body}\n")
    return p


def test_catalogue_loads_and_every_template_is_linted():
    cat = catalogue()
    assert "Q-META-1" in cat
    for t in cat.values():
        assert "LIMIT" in t.text.upper()


@pytest.mark.parametrize(
    "body,msg",
    [
        ("MATCH (n) RETURN n.id ORDER BY n.id", "literal LIMIT"),
        ("MATCH (n) RETURN n.id ORDER BY n.id LIMIT 500", "LIMIT must be"),
        ("MATCH (n) RETURN n.id ORDER BY n.id LIMIT $k", "literal LIMIT"),
        ("MATCH (n) RETURN n.id LIMIT 5", "ORDER BY"),
        ("MATCH (a)-[:R*]->(b) RETURN b.id ORDER BY b.id LIMIT 5", "unbounded"),
        ("MATCH (a)-[:R*1..]->(b) RETURN b.id ORDER BY b.id LIMIT 5", "unbounded"),
        ("CALL algo.BFS(n, 2, 'R') YIELD nodes RETURN nodes ORDER BY 1 LIMIT 5", "placeholders"),
        ("MATCH (n) SET n.x = 1 RETURN n.id ORDER BY n.id LIMIT 5", "write clause"),
        ("MATCH (n)\nOPTIONAL MATCH (n)-[:R]->(m)\nWHERE m.x > 1\nRETURN n.id ORDER BY n.id LIMIT 5", "OPTIONAL MATCH"),
    ],
)
def test_lint_rejects(tmp_path, body, msg):
    with pytest.raises(TemplateLintError, match=msg):
        parse(_write(tmp_path, body))


def test_bounded_varlen_and_marked_optional_where_pass(tmp_path):
    body = (
        "MATCH (a {id:$id})-[:R*1..6]->(b)\n"
        "OPTIONAL MATCH (b)-[:S]->(c)\n"
        "WHERE c.ok // lint: optional-where-ok\n"
        "RETURN b.id AS id ORDER BY id LIMIT 10"
    )
    t = parse(_write(tmp_path, body))
    assert t.id == "T-1"


def test_algo_placeholder_resolves_to_pinned_name(tmp_path):
    t = parse(_write(tmp_path, "MATCH (s {id:$id}) CALL {algo:bfs}(s, 2, 'R') YIELD nodes RETURN size(nodes) AS n LIMIT 1", "single-row"))
    assert "algo.BFS(" in t.text


def test_string_literals_do_not_trip_write_lint(tmp_path):
    t = parse(_write(tmp_path, "MATCH (n {kind:'CREATE SET'}) RETURN n.id AS id ORDER BY id LIMIT 3"))
    assert t.id == "T-1"


@pytest.mark.parametrize(
    "body,msg",
    [
        ("MATCH (a)-[:R* {ok:true}]->(b) RETURN b.id ORDER BY b.id LIMIT 5", "unbounded"),
        ("MATCH (a)-[:R*1.. {ok:true}]->(b) RETURN b.id ORDER BY b.id LIMIT 5", "unbounded"),
        ("MATCH (a) RETURN a.id AS id ORDER BY id LIMIT 5 UNION MATCH (b) RETURN b.id AS id ORDER BY id LIMIT 5", "UNION"),
        ("CALL db.idx.fulltext.createNodeIndex('S', 'n') RETURN 1 AS x ORDER BY x LIMIT 1", "not allowed"),
        ("MATCH (n) RETURN n.id ORDER BY n.id LIMIT toInteger($k)", "LIMIT"),
        ("MATCH (n)\nOPTIONAL MATCH (n)-[:R]->(m) WHERE m.x > 1\nRETURN n.id ORDER BY n.id LIMIT 5", "OPTIONAL MATCH"),
        ("MATCH (n)\nOPTIONAL MATCH (n)-[:R]->(m)\n\nWHERE m.x > 1\nRETURN n.id ORDER BY n.id LIMIT 5", "OPTIONAL MATCH"),
    ],
)
def test_lint_review_gaps_closed(tmp_path, body, msg):
    with pytest.raises(TemplateLintError, match=msg):
        parse(_write(tmp_path, body))


def test_seen_column_may_not_echo_a_parameter(tmp_path):
    p = tmp_path / "t.cypher"
    p.write_text("// id: T-2\n// seen: cause\n// returns: single-row\nMATCH (n) RETURN $cause AS cause LIMIT 1\n")
    with pytest.raises(TemplateLintError, match="echoes a parameter"):
        parse(p)


def test_comment_stripping_keeps_urls_in_strings(tmp_path):
    t = parse(_write(tmp_path, "MATCH (n {url:'https://x.y/z'}) RETURN n.id AS id ORDER BY id LIMIT 3 // trailing"))
    assert "https://x.y/z" in t.text and "trailing" not in t.text


def test_optional_match_after_aggregating_with_is_rejected(tmp_path):
    body = ("MATCH (r:Run {id:$r})\nOPTIONAL MATCH (r)-[:A]->(n)\nWHERE n.x // lint: optional-where-ok\n"
            "WITH r, collect(n.id) AS xs\nOPTIONAL MATCH (r)-[:B]->(m)\nRETURN xs, collect(m.id) AS ms\nLIMIT 1")
    with pytest.raises(TemplateLintError, match="aggregating WITH"):
        parse(_write(tmp_path, body, "single-row"))


def test_multiple_comprehensions_with_relationship_filter_rejected(tmp_path):
    body = ("MATCH (c:Node {id:$t})\nRETURN [(o:P)-[oc:ON_CALL]->(:T)-[:OWNS]->(c) WHERE oc.from <= $now | o.id] AS a,\n"
            "  [(m:P)-[:MEMBER_OF]->(:T)-[:OWNS]->(c) | m.id] AS b\nLIMIT 1")
    with pytest.raises(TemplateLintError, match="relationship-variable filter"):
        parse(_write(tmp_path, body, "single-row"))


def test_named_relationship_comprehension_followed_by_another_rejected(tmp_path):
    body = ("MATCH (n:Node {id:$id})\nRETURN [(d:D)-[c:CHANGED]->(n) | c.at] AS a,\n"
            "  [(i:I)-[:AFFECTED]->(n) | i.id] AS b\nLIMIT 1")
    with pytest.raises(TemplateLintError, match="its own WITH clause"):
        parse(_write(tmp_path, body, "single-row"))


def test_named_relationship_comprehension_in_its_own_with_or_last_passes(tmp_path):
    split = ("MATCH (n:Node {id:$id})\nWITH n, [(d:D)-[c:CHANGED]->(n) | c.at] AS a\n"
             "RETURN a, [(i:I)-[:AFFECTED]->(n) | i.id] AS b\nLIMIT 1")
    last = ("MATCH (n:Node {id:$id})\nRETURN [(i:I)-[:AFFECTED]->(n) | i.id] AS b,\n"
            "  [(d:D)-[c:CHANGED]->(n) | c.at] AS a\nLIMIT 1")
    for body in (split, last):
        parse(_write(tmp_path, body, "single-row"))


@pytest.mark.parametrize("body,msg", [
    # aggregate on a continuation line (review M12): #11 and #7 must still see the aggregating WITH
    ("MATCH (t:T)-[:OWNS]->(n)\nWITH t,\n  collect(n.id) AS xs\n"
     "RETURN [(p:P)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 AND p.active | p.id] AS a ORDER BY a LIMIT 5", "mixes relationship"),
    ("MATCH (r:Run)\nWITH r,\n count(r) AS c\nOPTIONAL MATCH (r)-[:A]->(x)\nRETURN c ORDER BY c LIMIT 1", "aggregating WITH"),
    # untyped relationship variable, `[ (` spacing and a path variable all trigger #9
    ("MATCH (n:N {id:$id})\nRETURN [(t:T)-[o]->(n) | o.from] AS a, [(i:I)-[:AFFECTED]->(n) | i.id] AS b ORDER BY a LIMIT 1",
     "its own WITH clause"),
    ("MATCH (n:N {id:$id})\nRETURN [ (t:T)-[o:OWNED_AT]->(n) | o.from] AS a, [ (i:I)-[:AFFECTED]->(n) | i.id] AS b ORDER BY a LIMIT 1",
     "its own WITH clause"),
    ("MATCH (n:N {id:$id})\nRETURN [p = (t:T)-[o:OWNED_AT]->(n) | o.from] AS a, [(i:I)-[:AFFECTED]->(n) | i.id] AS b ORDER BY a LIMIT 1",
     "its own WITH clause"),
])
def test_engine_bug_rules_survive_formatting(tmp_path, body, msg):
    with pytest.raises(TemplateLintError, match=msg):
        parse(_write(tmp_path, body, "rows"))


@pytest.mark.parametrize("body", [
    # docs/upstream/13: after an aggregating WITH, a filtered comprehension returns [] when an (OPTIONAL) MATCH sits
    # next to the first MATCH, or when its WHERE filters on a node (all observed on 6.0.2)
    "MATCH (t:T)-[:OWNS]->(n)\nOPTIONAL MATCH (s:S)-[:FOR]->(n)\nWITH t, collect(n.id) AS o\n"
    "RETURN o, [(p:P)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 | p.id] AS a ORDER BY a LIMIT 5",
    "MATCH (t:T)-[:OWNS]->(n)\nMATCH (s:S)-[:FOR]->(n)\nWITH t, collect(n.id) AS o\n"
    "RETURN o, [(p:P)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 | p.id] AS a ORDER BY a LIMIT 5",
    "MATCH (t:T)-[:OWNS]->(n)\nWITH t, collect(n.id) AS o\nRETURN o, [(p:P)-[:ON_CALL]->(t) WHERE p.active | p.id] AS a ORDER BY a LIMIT 5",
])
def test_filtered_comprehension_after_aggregation_needs_the_working_shape(tmp_path, body):
    with pytest.raises(TemplateLintError, match="upstream/13"):
        parse(_write(tmp_path, body))


def test_filtered_comprehension_after_aggregation_working_shape_passes(tmp_path):
    body = ("MATCH (t:T)-[:OWNS]->(n)\nWHERE n.id IN $ids\nWITH t, collect(n.id) AS o\n"
            "RETURN o, [x IN [(p:P)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND $now < oc.to | p] WHERE x.active | x.id] AS a "
            "ORDER BY a LIMIT 5")
    parse(_write(tmp_path, body))


def test_quote_in_a_comment_line_is_rejected(tmp_path):
    body = "// the component's own row\nMATCH (n) RETURN n.id AS id ORDER BY id LIMIT 5"
    with pytest.raises(TemplateLintError, match="quote character"):
        parse(_write(tmp_path, body))


def test_read_subquery_call_is_allowed_and_its_inner_calls_still_checked(tmp_path):
    ok = ("MATCH (s:N {id:$id})\nCALL { WITH s CALL {algo:bfs}(s, 8, 'R') YIELD nodes UNWIND nodes AS x RETURN collect(x) AS r }\n"
          "UNWIND r + [s] AS n RETURN n.id AS id ORDER BY id LIMIT 5")
    assert "algo.BFS(" in parse(_write(tmp_path, ok)).text
    bad = ("MATCH (s:N {id:$id})\nCALL { WITH s CALL db.idx.fulltext.createNodeIndex('S', 'n') RETURN 1 AS r }\n"
           "RETURN r ORDER BY r LIMIT 5")
    with pytest.raises(TemplateLintError, match="not allowed"):
        parse(_write(tmp_path, bad))


def test_with_then_two_matches_ignoring_carried_rows_is_rejected(tmp_path):
    body = ("UNWIND $ids AS sid\nMATCH (d:Deploy) WHERE d.at > 0\nMATCH (x:Node {id: sid})\n"
            "RETURN x.id AS id ORDER BY id LIMIT 5")
    with pytest.raises(TemplateLintError, match="engine bug #16"):
        parse(_write(tmp_path, body, "rows"))


def test_intake_and_primary_grouping_share_one_hop_bound():
    """Q-PRIMARY-1 (the gate's independent alerts) applies INTAKE's carry rule (Q-STORM-EDGES, Q-STORM-ATTACH): it must
    use the same hop bound, or the gate could call a target a consequence over a path INTAKE never grouped."""
    import re

    cat = catalogue()
    bounds = {tid: {int(m) for m in re.findall(r"PROPAGATES_TO\*\d+\.\.(\d+)", cat[tid].text)}
              for tid in ("Q-PRIMARY-1", "Q-STORM-EDGES", "Q-STORM-ATTACH")}
    assert all(len(b) == 1 for b in bounds.values()) and len(set.union(*bounds.values())) == 1, bounds


def test_call_with_where_after_a_top_level_optional_match_is_rejected(tmp_path):
    """Engine bug #17 (docs/upstream/17): on 6.0.2 the subquery's filter on a node it binds can run before that node is
    bound, and every row is dropped silently."""
    bad = ("MATCH (c:Node {id:$id})\nOPTIONAL MATCH (t:Team)-[:OWNS]->(c)\n"
           "CALL {\n  WITH c\n  MATCH (c)<-[:PART_OF]-(f:File)<-[:TOUCHES]-(cm:Commit)\n  WHERE cm.at > 0\n"
           "  RETURN count(cm) AS n\n}\nRETURN n\nLIMIT 1")
    with pytest.raises(TemplateLintError, match="#17"):
        parse(_write(tmp_path, bad, returns="single-row"))
    inline = ("MATCH (c:Node {id:$id})\nOPTIONAL MATCH (t:Team)-[:OWNS]->(c)\n"
              "CALL {\n  WITH c\n  MATCH (c)<-[:PART_OF]-(f:File)<-[:TOUCHES]-(cm:Commit {tenant:'acme'})\n"
              "  RETURN count(cm) AS n\n}\nRETURN n\nLIMIT 1")  # an inline map is a filter too (0 instead of 155 on acme)
    with pytest.raises(TemplateLintError, match="#17"):
        parse(_write(tmp_path, inline, returns="single-row"))


@pytest.mark.parametrize("body", [
    # the optional part inside its own subquery (the fix the who_fixes templates use)
    "MATCH (c:Node {id:$id})\nCALL {\n  WITH c\n  OPTIONAL MATCH (t:Team)-[:OWNS]->(c)\n  RETURN collect(t.id) AS ts\n}\n"
    "CALL {\n  WITH c\n  MATCH (f:File)-[:PART_OF]->(c)\n  WHERE f.id <> ''\n  RETURN count(f) AS n\n}\nRETURN ts, n\nLIMIT 1",
    # a subquery without WHERE after a top-level OPTIONAL MATCH
    "MATCH (c:Node {id:$id})\nOPTIONAL MATCH (t:Team)-[:OWNS]->(c)\nCALL {\n  WITH c\n  MATCH (f:File)-[:PART_OF]->(c)\n"
    "  RETURN count(f) AS n\n}\nRETURN n\nLIMIT 1",
])
def test_optional_parts_read_safely_pass(tmp_path, body):
    parse(_write(tmp_path, body, returns="single-row"))


def test_inline_map_reading_the_previous_match_is_rejected(tmp_path):
    """Engine bug #18 (docs/upstream/18): silently empty without an index, an error with one."""
    bad = "MATCH (p:P {id:$id})\nMATCH (a:Node {id: p.src})\nRETURN a.id AS id\nORDER BY id\nLIMIT 5"
    with pytest.raises(TemplateLintError, match="#18"):
        parse(_write(tmp_path, bad))
    for ok in ("MATCH (p:P {id:$id})\nMATCH (a:Node)\nWHERE a.id = p.src\nRETURN a.id AS id\nORDER BY id\nLIMIT 5",
               "MATCH (p:P {id:$id})\nWITH p\nMATCH (a:Node {id: p.src})\nRETURN a.id AS id\nORDER BY id\nLIMIT 5"):
        parse(_write(tmp_path, ok))


def test_no_write_query_has_the_engine_bug_18_shape():
    """The rule found its first instance in a write query (the learned-edge approval): every W_* query is checked too."""
    from faultline.graph import writes
    from faultline.graph.templates import inline_map_after_match, mask_strings

    queries = {k: v for k, v in vars(writes).items() if k.startswith("W_") and isinstance(v, str)}
    assert len(queries) > 20
    assert not [k for k, q in queries.items() if inline_map_after_match(mask_strings(q))]
    assert inline_map_after_match("MATCH (p:P {id: $x}) MATCH (a:Node {id: p.src}) RETURN a")


def test_match_after_call_subquery_reusing_a_bound_variable_is_rejected():
    """Engine bug #19 (docs/upstream/19): the MATCH ignores the binding and matches every node."""
    bad = ("MATCH (s:Node) WHERE s.id IN $ids\nCALL { WITH s RETURN 1 AS x }\nWITH s, x\n"
           "MATCH (u:Node)-[:PROPAGATES_TO*1..8]->(s)\nRETURN u.id AS u ORDER BY u LIMIT 10")
    with pytest.raises(TemplateLintError, match="#19"):
        lint("T", bad, "", ())
    # the variable dropped by a WITH and re-bound with its own filter (Q-PRIMARY-1's shape) is a new binding: allowed
    ok = ("MATCH (t:Node) WHERE t.id IN $ids\nCALL { WITH t RETURN 1 AS x }\nWITH collect(x) AS xs\n"
          "MATCH (t:Node) WHERE t.id IN $ids\nRETURN t.id AS t, xs ORDER BY t LIMIT 10")
    lint("T", ok, "", ())
    # MATCH first, then the subqueries (Q-GATE-UPSTREAM's shape): allowed
    lint("T", "MATCH (s:Node) WHERE s.id IN $ids\nMATCH (u:Node)-[:PROPAGATES_TO*1..8]->(s)\nWITH DISTINCT u, s\n"
              "CALL { WITH s RETURN 1 AS x }\nRETURN u.id AS u, x ORDER BY u LIMIT 10", "", ())


def test_comprehension_filter_then_disconnected_match_is_refused():
    """docs/upstream/20 (found writing the on-call escalation): a MATCH whose WHERE holds a pattern comprehension,
    followed by a MATCH that uses none of its variables, silently drops the row on 6.0.2."""
    from faultline.graph.templates import TemplateLintError, lint

    bad = "MATCH (n:N {id:$a}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0 MATCH (p:P {id:$p}) RETURN n.id AS id ORDER BY id LIMIT 1"
    with pytest.raises(TemplateLintError, match="engine bug #20"):
        lint("T", bad, "rows", ())
    # the forms that work: the other MATCH first, a connected second MATCH, the comprehension in a WITH
    lint("T", "MATCH (p:P {id:$p}) MATCH (n:N {id:$a}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0 RETURN n.id AS id ORDER BY id LIMIT 1", "rows", ())
    lint("T", "MATCH (n:N {id:$a}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0 MATCH (n)-[:T]->(m) RETURN m.id AS id ORDER BY id LIMIT 1", "rows", ())
    lint("T", "MATCH (n:N {id:$a}) WITH n, size([(n)<-[:R]-(x:X) | x]) AS k WHERE k = 0 MATCH (p:P {id:$p}) "
              "RETURN p.id AS id ORDER BY id LIMIT 1", "rows", ())
