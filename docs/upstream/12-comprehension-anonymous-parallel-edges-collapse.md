# Pattern comprehension over an anonymous relationship collapses parallel edges (6.0.2)

**Status:** known upstream as [FalkorDB#2501](https://github.com/FalkorDB/FalkorDB/issues/2501) (a duplicate of #1848); comment prepared, not posted.

A pattern comprehension should produce one element per matched path. With an **anonymous** relationship, FalkorDB 6.0.2 produces one element per distinct end node, so parallel edges between the same two nodes are counted once. Naming the relationship variable restores per-path results.

```
MATCH (t:Team {id:'team-checkout'})
RETURN size([(p:Person)-[:ON_CALL]->(t) | p.id])   AS anonymous,   -- 5
       size([(p:Person)-[r:ON_CALL]->(t) | p.id])  AS named         -- 22 (correct: 22 ON_CALL edges, 5 people)
```

The equivalent `MATCH (p:Person)-[oc:ON_CALL]->(t:Team {id:'team-checkout'}) RETURN count(oc)` returns 22. Projecting a constant (`| 1`) behaves like the anonymous case (5).

**Impact.** Counts silently drop when nodes are connected by several edges of one type (rota periods, per-incident VIOLATES edges).
**Workaround.** Name the relationship variable when per-edge results matter, and keep that comprehension last in its projection (see #9).
**Expected.** One element per path, as in the MATCH form and the openCypher semantics of pattern comprehensions.
