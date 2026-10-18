# A relationship range index makes anchored and labelled traversals 13× to 240× slower, and one scan times out (6.0.2): performance cliff

**Status:** filed as [FalkorDB#3376](https://github.com/FalkorDB/FalkorDB/issues/3376).

Found on 2026-10-17 while putting more of FalkorDB's engine features to use. Verified on the pinned 6.0.2 digest on a
throwaway graph (numbers are single-run probes on a laptop, see docs/FALKORDB_COMPAT.md; re-measure before quoting).

```cypher
UNWIND range(1, 3000) AS i CREATE (:N {id: i});
CREATE INDEX FOR (n:N) ON (n.id);
UNWIND range(1, 60000) AS k WITH k, (k * 7919) % 3000 + 1 AS a, (k * 104729) % 3000 + 1 AS b
  MATCH (x:N {id: a}), (y:N {id: b}) CREATE (x)-[:P {v: k}]->(y);

// run each before and after:  CREATE INDEX FOR ()-[r:P]-() ON (r.v)
MATCH (a:N)-[r:P]->(b:N) WHERE r.v > 30000 RETURN count(r);          // 1: labelled endpoints
MATCH (a:N {id: 7})-[r:P]->(b) WHERE r.v > 30000 RETURN count(r);    // 2: anchored
MATCH ()-[r:P]->() WHERE r.v > 59000 RETURN count(r);                // 3: anonymous endpoints, selective
```

| Query | Before the edge index | After |
|---|---|---|
| 1 labelled endpoints, non-selective | about 4.7 ms | timed out at 5 s |
| 2 anchored on one node | about 0.014 ms | about 3.4 ms |
| 3 anonymous endpoints, selective | about 3.9 ms | about 0.05 ms (the index helps) |

The plan after the index puts `Edge By Index Scan` under `Node By Label Scan` / `Node By Index Scan` for queries 1 and 2:
the index is used even when an anchored or labelled node scan would bound the work far more tightly.

**Request.** Choose `Edge By Index Scan` only when it drives the scan (anonymous or unselective endpoints), or cost it
against the expansion from a bound node; at least document that an edge index can slow anchored traversals.

**Impact for Faultline:** none shipped. Almost every template is anchored on an id, so Faultline creates no relationship
index (docs/FALKORDB_COMPAT.md); revisit after a fix, behind a PROFILE A/B.
