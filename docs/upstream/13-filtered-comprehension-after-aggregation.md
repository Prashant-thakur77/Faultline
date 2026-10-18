# [Bug] Filtered pattern comprehension returns [] after an aggregating WITH (6.0.2), beyond #11

**Status:** comment prepared for [FalkorDB#3004](https://github.com/FalkorDB/FalkorDB/issues/3004), not posted. Found while building the obligation clock (2026-10-13).

**Engine:** `falkordb/falkordb:6.0.2` @ `sha256:107455e8…` (module 60002)

## Reproduce
```cypher
CREATE (p:Person {id:'p', active:true})-[:ON_CALL {from:0, to:10}]->(t:Team {id:'t'}),
       (t)-[:OWNS]->(n:N {id:'x'}), (:S {id:'s'})-[:FOR]->(n)
```

| # | query shape (all end `WITH t, collect(n.id) AS o RETURN o, <comprehension>`) | result | expected |
|---|---|---|---|
| A | `MATCH (t:Team)-[:OWNS]->(n:N)` … `[x IN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 AND 1 < oc.to \| p] WHERE x.active \| x.id]` | `['p']` | `['p']` |
| B | A plus `OPTIONAL MATCH (s:S)-[:FOR]->(n)` before the WITH | `[]` | `['p']` |
| B1 | B with `[(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 \| p.id]` | `[]` | `['p']` |
| B4 | B1, but the OPTIONAL MATCH matches nothing (`(s:Nope)`) | `[]` | `['p']` |
| B5 | B1 with a plain second `MATCH` instead of OPTIONAL MATCH | `[]` | `['p']` |
| B7 | one MATCH with two patterns (`MATCH (t)-[:OWNS]->(n), (s:S)-[:FOR]->(n)`) + B1's comprehension | `[]` | `['p']` |
| B9 | single MATCH, `[(p:Person)-[:ON_CALL]->(t) WHERE p.active \| p.id]` (node-only filter) | `[]` | `['p']` |
| C | B with no WHERE in the comprehension | `['p']` | `['p']` |
| B3 | B1 with a non-aggregating `WITH t, n` | `['p']` | `['p']` |
| B6 | B, with the comprehension rewritten as `MATCH … WHERE … RETURN o, collect(p.id)` | `['p']` | `['p']` |

A double aggregation in front of the same comprehension (`WITH t, n, count(DISTINCT o) … WITH t, collect(…)`) failed
with `Variable oc not found` instead of returning a value.

## What we observed
After an aggregating WITH, a pattern comprehension with a WHERE returns `[]` silently unless **exactly one MATCH
clause** (one pattern, no OPTIONAL MATCH) precedes the aggregation **and** the WHERE references only the
comprehension's relationship variable. #11 (mixed relationship + node predicates) is one instance of this.

## Workaround (what Faultline does)
- The template lint (`backend/faultline/graph/templates/__init__.py`) rejects every other shape.
- Node filters go in an outer list comprehension (`[x IN [(…) WHERE r.prop … | p] WHERE x.active | x.id]`).
- The obligation flag for the notify list is not joined into Q-NOTIFY-1; it comes from the obligation clock's
  own templates (Q-OBL-SLO / Q-OBL-CUST).
