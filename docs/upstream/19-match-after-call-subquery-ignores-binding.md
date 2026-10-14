# A MATCH after a CALL {} subquery ignores a variable bound before the subquery (silently wrong rows)

**Engine:** FalkorDB 6.0.2 (pinned digest `sha256:107455e8…`). **Found by:** the deep bench (`evals/deep_bench.py`), through a new gate template that returned no rows. **Status:** draft, not yet filed (the owner files upstream issues).

## Minimal reproduction (any graph with a few `PROPAGATES_TO` edges into node `frontend`)
```cypher
// expected: one row, 'frontend'
MATCH (s:Node) WHERE s.id IN ['frontend']
CALL { WITH s RETURN 0.5 AS x }
WITH s, x
MATCH (u:Node)-[:PROPAGATES_TO*1..8]->(s)
RETURN DISTINCT s.id
```
Actual on 6.0.2: one row per node that has any incoming `PROPAGATES_TO` path (20 rows on our acme tenant). The second MATCH treats `s` as unbound.

Controls on the same graph:
- without the `CALL {}` (a plain `WITH s, 0.5 AS x`): one row, as expected;
- with `WITH s, x WHERE x > 0.1` after the subquery: same wrong result;
- a variable projected before the subquery survives it (`WITH s, 0.5 AS x CALL { WITH s RETURN 1 AS y } RETURN x, y` is correct): only re-anchoring a pattern on the earlier binding is affected.

## Impact
Silently wrong rows: values computed for the wrongly re-bound nodes come back null, and filters on them drop everything, so a query can return either too many rows or none. No error.

## Workaround used in Faultline
Every MATCH that anchors on an earlier binding comes before the first `CALL {}` subquery; subqueries only read (Q-GATE-UPSTREAM). The template lint rejects a top-level MATCH after a subquery that re-uses a node variable still in scope (`backend/faultline/graph/templates/__init__.py`, test `test_match_after_call_subquery_reusing_a_bound_variable_is_rejected`). No shipped template had the shape.
