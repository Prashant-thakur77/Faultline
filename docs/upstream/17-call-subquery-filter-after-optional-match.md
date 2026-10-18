# A CALL {} subquery after OPTIONAL MATCH filters on a node before binding it (6.0.2): silent empty result

**Status:** related to [FalkorDB#3037](https://github.com/FalkorDB/FalkorDB/issues/3037); comment prepared, not posted.

Found 2026-10-13 while moving `who_fixes`' inputs into Cypher. Verified on the pinned 6.0.2 digest only
(docs/FALKORDB_COMPAT.md). No index needed.

```cypher
CREATE (c:N {id:'c'}), (f:F {id:'f'})-[:P]->(c), (m:M {id:'m', at:5})-[:T]->(f), (t:Tm {id:'t'})-[:O]->(c);

// A: expected [[1]]; got [[0]]
MATCH (c:N {id:'c'})
OPTIONAL MATCH (t:Tm)-[:O]->(c)
CALL { WITH c MATCH (c)<-[:P]-(f:F)<-[:T]-(m:M) WHERE m.at > 0 RETURN count(m) AS n }
RETURN n;

// B: the same without the OPTIONAL MATCH: [[1]] (correct)
MATCH (c:N {id:'c'})
CALL { WITH c MATCH (c)<-[:P]-(f:F)<-[:T]-(m:M) WHERE m.at > 0 RETURN count(m) AS n }
RETURN n;
```

With the OPTIONAL MATCH, the subquery's plan puts `Filter (m.at > 0)` below `Conditional Traverse (m)->(f)`, the
operation that binds `m`, so the filter sees an unbound `m` and drops every row. Without it, the Filter sits above both
traversals. On the real graph, filters on the first hop's node (`f`) and on the last node of a three-hop pattern were
still correct; a filter on the node bound by the second traversal was not (`cm.at`, `cm.id IS NOT NULL`, `cm.at > 0`).
A second form: in a longer query (several CALL subqueries, then `UNWIND … WITH DISTINCT … MATCH (p)`), a per-row
subquery `CALL { WITH p, c MATCH (p)-[:AUTHORED]->(cm:Commit)-[:TOUCHES]->(:File)-[:PART_OF]->(c) WHERE cm.at >= $since
RETURN count(DISTINCT cm) }` also returned 0, while the same subquery in a short query returned the right count.

**Impact for Faultline:** none shipped. The two new `who_fixes` templates hit it during development (every author
vanished) and now read the optional part (the owner team) in its own subquery, and compute per-person counts in the
first subqueries instead of a filtered per-row subquery. A template-lint rule rejects a CALL subquery with WHERE after a
top-level OPTIONAL MATCH (`graph/templates/__init__.py`, test `test_call_with_where_after_a_top_level_optional_match_is_rejected`);
no other template has the shape. The rule also rejects an inline property map on a node the subquery binds
(`(cm:Commit {tenant:'acme'})` returned 0 instead of 155 on the same graph). The second form above is not linted: it is
documented here and avoided by computing per-row counts in the first subqueries.
