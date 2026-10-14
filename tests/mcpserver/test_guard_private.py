"""Review round 5, minor 6: the text2cypher guard's private-data policy (hosted MCP run_cypher_readonly and the brain's
tier 3). Brain sessions and turns are per user and a run token hash is a capability: no guarded query may read them,
in any spelling, and the rows that come back are filtered whatever the query looked like."""

import pytest

from faultline.graph import guard as G

DENIED = [
    "MATCH (s:Session) RETURN s.id",
    "MATCH (t:Turn) RETURN t.seq",
    "MATCH (t:`Turn`) RETURN t.seq",
    "MATCH (n:Node) WHERE n.text CONTAINS 'refund' RETURN n.id",
    "MATCH (r:Run) RETURN r.token_sha",
    "MATCH (r:Run) RETURN r {.token_sha}",
    "MATCH (r:Run) RETURN r { .id, .token_sha }",
    "MATCH (n {user: 'p-030'}) RETURN n.id",
    "MATCH (n) RETURN n['text']",
    "MATCH (n) WHERE 'Turn' IN labels(n) RETURN n.id",
    "MATCH (n) WHERE 'token_sha' IN keys(n) RETURN n.id",
    "MATCH (r:Run) RETURN properties(r)",
    "MATCH (a)-[:HAS_TURN]->(b) RETURN b.seq",
    "MATCH (n) WHERE n.id STARTS WITH 'sess-' RETURN n.id",
    "MATCH (n) RETURN n[$k]",
    "MATCH (n:Node) RETURN n.refs",
]
ALLOWED = [
    "MATCH (s:Service) RETURN s.id",
    "MATCH (p:Person) RETURN p.role",
    "MATCH (n:Node) WHERE flex.text.jaroWinkler(n.id, 'paymnt') > 0.9 RETURN n.id",
    "MATCH (r:Run) RETURN r.id, keys(r)",
]


@pytest.mark.parametrize("q", DENIED)
def test_private_labels_and_properties_are_refused_in_any_form(q):
    with pytest.raises(G.GuardError):
        G.guard(q)


@pytest.mark.parametrize("q", ALLOWED)
def test_ordinary_queries_still_pass(q):
    G.guard(q)


def test_parameters_cannot_name_private_data():
    for p in ({"l": "Turn"}, {"k": "token_sha"}, {"ids": ["x", "sess-abc"]}, {"m": {"x": "text"}}):
        with pytest.raises(G.GuardError):
            G.check_params(p)
    G.check_params({"id": "checkout", "n": 3})


def test_rows_with_private_nodes_or_session_ids_are_dropped_and_private_properties_stripped():
    rows = [
        {"n": {"_labels": ["Turn"], "id": "sess-x-t1", "text": "my refund question"}},
        {"n": {"_labels": ["Session"], "id": "sess-x", "user": "u1"}},
        {"r": {"_labels": ["Run"], "id": "run-1", "token_sha": "ab" * 32}},
        {"e": {"_type": "HAS_TURN", "k": "t"}},
        {"ids": ["checkout", "sess-y"]},
        {"x": 1, "label": "Service"},
    ]
    out, dropped = G.redact_rows(rows)
    assert dropped == 4
    assert out == [{"r": {"_labels": ["Run"], "id": "run-1"}}, {"x": 1, "label": "Service"}]


def test_run_guarded_applies_the_policy_to_params_and_rows(monkeypatch):
    """The RO wrapper's text2cypher path checks parameters and filters rows (no engine needed: the client is faked)."""
    from faultline.graph import ro as ro_mod

    class _Res:
        header = [[1, "n"]]
        result_set = [[{"_labels": ["Turn"], "id": "sess-z-t1"}], [{"_labels": ["Service"], "id": "cart"}]]

    class _G:
        def explain(self, q, params):
            return []

        def ro_query(self, q, params=None, timeout=None):
            return _Res()

    monkeypatch.setattr(ro_mod.client, "ro_graph", lambda tenant, graph: _G())
    monkeypatch.setattr(ro_mod, "to_plain", lambda v: v)
    r = ro_mod.RO("acme")
    with pytest.raises(G.GuardError):
        r.run_guarded("MATCH (n:Service) WHERE n.id = $x RETURN n", {"x": "Session"})
    res = r.run_guarded("MATCH (n:Service) RETURN n", {})
    assert res.rows == [{"n": {"_labels": ["Service"], "id": "cart"}}]
