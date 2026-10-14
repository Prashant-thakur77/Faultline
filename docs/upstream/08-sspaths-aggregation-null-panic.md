# Server panic (process exits): algo.SSpaths + aggregation grouped with a null property (6.0.2)

**Severity:** a single read-only query (`GRAPH.RO_QUERY`) crashes the server: `FalkorDB panic: panicked at src/reply.rs:655:58: called Option::unwrap() on a None value` (in `falkordb::reply::reply_compact`), and the process exits.

**Image:** falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6 (6.0.2), Python client 1.7.1 (compact replies).

```
GRAPH.QUERY g "CREATE (:K:Node {id:'k', tier:1})-[:P {cap:1.0, w:1}]->(:D:Node {id:'d'})"
GRAPH.RO_QUERY g "MATCH (s:Node {id:'k'}) CALL algo.SSpaths({sourceNode: s, relTypes: ['P'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path WITH last(nodes(path)) AS n, length(path) AS hops RETURN n.id AS id, min(hops), n.tier AS tier" --compact
```
`n.tier` is null on `d`. Variants that do **not** crash: the same aggregation without the null column; `coalesce(n.tier, 0)`; aggregating per node first (`WITH n, min(length(path)) AS h RETURN n.id, h, n.tier`); the same shape with a MATCH path or `algo.BFS` instead of `algo.SSpaths`.
**Workaround in Faultline:** every SSpaths template aggregates per node before projecting properties (template header notes reference this file).
