# algo.betweenness ranks the wrong node on a 5-node path (v4.22.0)

**Image:** falkordb/falkordb@sha256:4ac83f55062d364dcf151692635138b0bd2e12578019a56eb86ef53d067b116b (v4.22.0)

```
GRAPH.QUERY g "UNWIND [['a','b'],['b','c'],['c','d'],['d','e']] AS e MERGE (x:N {id:e[0]}) MERGE (y:N {id:e[1]}) MERGE (x)-[:R]->(y)"
GRAPH.RO_QUERY g "CALL algo.betweenness({nodeLabels:['N'], relationshipTypes:['R'], samplingSize:64, samplingSeed:42}) YIELD node, score RETURN node.id, score ORDER BY score DESC"
```
**Expected (directed Brandes):** c = 4, b = d = 3, a = e = 0. 6.0.2 returns c = 4.0 first.
**Actual on v4.22.0:** b = 6.0 first (deterministic across runs).
