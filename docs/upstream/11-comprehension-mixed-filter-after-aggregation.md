# [Bug] Pattern comprehension with a relationship AND a node predicate returns [] after an aggregating WITH (6.0.2)

**Status:** comment prepared for [FalkorDB#3004](https://github.com/FalkorDB/FalkorDB/issues/3004), not posted.

**Engine:** `falkordb/falkordb:6.0.2` @ `sha256:107455e8…` (module 60002)

## Reproduce
```cypher
// data: (p:Person {active:true})-[:ON_CALL {from:0, to:9e15}]->(t:Team {id:'t'}), (t)-[:OWNS]->(n:Node {id:'x'})
MATCH (t:Team)-[:OWNS]->(n:Node) WHERE n.id IN ['x']
WITH t, collect(DISTINCT n.id) AS o
RETURN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= 1 AND 1 < oc.to AND p.active | p.id]
```
- **Expected:** `[<person id>]`
- **Actual:** `[]`

## What we observed
- **Without the node predicate** (`p.active`), the same comprehension returns the person.
- **Without the aggregating `WITH`**, it also works.
- **Only the relationship predicates** (`oc.from`, `oc.to`): works.
- **Only the node predicate** (`p.active`): works.
- **Both together after the aggregation:** returns `[]`, silently.

## Workaround (what Faultline does)
Filter the nodes in an outer list comprehension:
```cypher
[x IN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND $now < oc.to | p] WHERE x.active | x.id]
```
Our template lint rejects the failing shape (`backend/faultline/graph/templates/__init__.py`).
