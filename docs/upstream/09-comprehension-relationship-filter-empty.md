# Pattern comprehension with a relationship-property filter returns [] when another comprehension follows (6.0.2)

```
MATCH (c:Node {id:$t})
RETURN [(o:Person)-[oc:ON_CALL]->(:Team)-[:OWNS]->(c) WHERE oc.from <= $now AND $now < oc.to | o.id] AS oncall,
       [(t:Team)-[:OWNS]->(c) | t.id] AS owner
```
On the acme graph this returns `oncall = []`. The same comprehension alone, or placed **after** the other one, returns `['p-030']` (the correct answer, also returned by the equivalent OPTIONAL MATCH form). The trigger appears to be a WHERE on a relationship variable inside a comprehension followed by another comprehension that matches the same anchor node.

## Narrower trigger (found 2026-10-13, same engine)
The WHERE is not needed. A **named relationship variable** in one pattern comprehension is enough to empty every comprehension that follows it in the same projection, when the later one traverses a different relationship type:

```
MATCH (n:Node {id:$id})
RETURN size([(d:Deploy)-[c:CHANGED]->(n) | c.at]) AS deploys,       -- 12 (correct)
       [(i:Incident)-[:AFFECTED]->(n) | i.id] AS incidents             -- [] (expected 6)
```

| Form | deploys | incidents |
|---|---|---|
| `-[c:CHANGED]->` first, then `-[:AFFECTED]->` | 12 | **0** |
| `-[:CHANGED]->` (unnamed) first, then `-[a:AFFECTED]->` | 12 | 6 |
| `-[a:AFFECTED]->` first, then `-[c:CHANGED]->` | **0** (second) | 6 |
| the same rel var name `r` reused in both | 12 | **0** |
| `-[c:CHANGED]->` then a second `CHANGED` comprehension | 12 | 12 |
| the two comprehensions in separate `WITH` clauses | 12 | 6 |

**Workaround:** put each comprehension that names a relationship variable in its own `WITH` clause, or make it the last comprehension of its projection. The template lint now rejects a comprehension that names a relationship variable when another comprehension follows it in the same projection.
