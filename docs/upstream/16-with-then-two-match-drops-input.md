# WITH/UNWIND followed by two MATCH clauses (the first disconnected) drops the WITH's rows (6.0.2): silent wrong result

Found by the scale benchmark (`evals/scale.py`) while moving `Q-SUS-1` onto the `Deploy.at` range index. Verified on the
pinned 6.0.2 digest only (docs/FALKORDB_COMPAT.md).

```cypher
CREATE INDEX FOR (d:D) ON (d.at);
CREATE (:N {id:'a'}) WITH 1 AS one UNWIND range(1,3) AS i CREATE (:D {at:i})-[:CH]->(:X {id:i});

// A: expected [[[1],'a',2], [[1],'a',3]]; got [] (the s.id filter sees null)
MATCH (s:N {id:'a'}) WITH s, [1] AS ups
MATCH (d:D) WHERE d.at >= 2
MATCH (d)-[:CH]->(x)
RETURN ups, s.id, d.at ORDER BY d.at;

// B: expected ups = [1]; got null on every row
WITH [1] AS ups MATCH (d:D) WHERE d.at >= 2 MATCH (d)-[:CH]->(x) RETURN ups, d.at;

// C: same with UNWIND: u is null
UNWIND [7] AS u MATCH (d:D) WHERE d.at >= 2 MATCH (d)-[:CH]->(x) RETURN u, d.at;
```

The plan for A is `Sort ← Project ← Conditional Traverse (d)->(x) ← Filter ← Node By Index Scan (d:D)`: the whole input
branch (`Node By Label Scan (s:N)` and the WITH projection) is gone, with no Cartesian Product or Apply. It does not need
an index (the same happens with a label scan as the first MATCH). These variants are correct:

- one combined pattern: `WITH s, [1] AS ups MATCH (d:D)-[:CH]->(x) WHERE d.at >= 2` (Cartesian Product with the input);
- a WITH between the two MATCH clauses: `… MATCH (d:D) WHERE d.at >= 2 WITH ups, s, d MATCH (d)-[:CH]->(x) …`;
- `OPTIONAL MATCH` as the second clause;
- the same clauses without the leading WITH/UNWIND (`MATCH (s) MATCH (d:D) … MATCH (d)-[…]->(x)`).

**Impact for Faultline:** none shipped. No product template has the pattern (checked with a clause scan over
`graph/templates/*.cypher`); `Q-SUS-1` uses the WITH-between form and says why in its header. A template-lint rule
(WITH/UNWIND → MATCH with no bound variable → MATCH) would keep it that way.

**Second form (found 2026-10-13 writing `Q-VERIFY-ALLOW`):** after an *aggregating* WITH, a single MATCH with a
multi-hop pattern whose `WHERE` references the projected variables evaluates them as null, so every row is filtered
out (silent empty result). On S14's graph:

```cypher
MATCH (me:Incident {id: $inc})-[:HYPOTHESIZES]->(:Hypothesis)-[:BLAMES]->(mc)-[:CHANGED|GATES]->(mo)
WITH collect(DISTINCT mc.id) AS my_causes
MATCH (i:Incident)-[:HYPOTHESIZES]->(:Hypothesis)-[:BLAMES]->(c)-[:CHANGED|GATES]->(o)
WHERE size(my_causes) = 1          // also `NOT c.id IN my_causes`, `c.id IN my_causes`: all return []
RETURN i.id
```

Not every shape is affected: Q-STORM-EDGES and Q-PRIMARY-1 (`WITH collect(…) AS region MATCH (u)-[r]->(v) WHERE
u.id IN region …`, one hop) return the right rows (live-tested). The trigger was not narrowed further than "a 4-hop
pattern after an aggregating WITH". `none(x IN my_causes WHERE x = c.id)` in the same position and the WITH-between form (`… MATCH (…) WITH i, c, o,
my_causes WHERE NOT c.id IN my_causes`) both return the expected rows. `Q-VERIFY-ALLOW` uses the WITH-between form and
says why in its header.
