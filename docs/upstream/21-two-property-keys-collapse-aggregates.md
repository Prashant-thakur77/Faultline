# Grouping a single-node MATCH by two properties returns the first aggregate in every aggregate column (6.0.2): silent wrong result

Found writing the contract-suggestion read (`Q-LEARN-SUGGEST`, M21): `events` came back as an integer. Verified on the
pinned 6.0.2 digest only (docs/FALKORDB_COMPAT.md); module `graph` version 60002.

```cypher
CREATE (:X {id:'a', a:'k', b:'h', c:1}), (:X {id:'b', a:'k', b:'h', c:2}), (:X {id:'c', a:'k', b:'z', c:3});

// A: expected [['k','h',2,['a','b']], ['k','z',1,['c']]]; got [['k','h',2,2], ['k','z',1,1]]
MATCH (x:X) RETURN x.a AS a, x.b AS b, count(x) AS n, collect(x.id) AS ids ORDER BY b;

// the same with the aggregates swapped: every column is the list
MATCH (x:X) WITH x.a AS a, x.b AS b, collect(x.id) AS ids, count(x) AS n RETURN a, b, n, ids ORDER BY b;
//   → [['k','h',['a','b'],['a','b']], ['k','z',['c'],['c']]]
// sum then collect: [['k','h',3.0,3.0], ['k','z',3.0,3.0]]  (the collect column repeats the sum)

// correct variants
MATCH (x:X) RETURN x.b AS b, count(x) AS n, collect(x.id) AS ids ORDER BY b;                // one grouping key
MATCH (x:X)-[:R]->(y:Y) RETURN x.a AS a, x.b AS b, count(x) AS n, collect(x.id) AS ids;    // a path, not a node scan
MATCH (x:X) WITH [x.a, x.b] AS key, count(x) AS n, collect(x.id) AS ids
RETURN key[0] AS a, key[1] AS b, n, ids;                                                    // ONE list grouping key
```

A second, related failure on the same shape: `RETURN … xs[0..20] AS xs … ORDER BY <grouping key>` after a WITH that
aggregates `count(DISTINCT …)` fails with `Invalid array range parameters.` (slice in its own WITH first: it passes).

**Impact for Faultline:** none shipped. `Q-LEARN-SUGGEST` / `Q-LEARN-SUGGESTS` group by one list key and slice in their
own WITH, with a comment. An audit of the other templates found no single-node scan grouped by two properties with two
or more aggregates (the eight two-key groupings all aggregate over a relationship pattern, which is not affected).
