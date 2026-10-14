// id: Q-BLAST-2
// (aggregate per node first, then project: FalkorDB 6.0.2 panics on SSpaths + aggregation grouped with a null property; docs/upstream/08)
// purpose: hop distance and bottleneck cap from $id to every reachable node (impact scoring input)
// seen: id
MATCH (s:Node {id:$id})
CALL {algo:sspaths}({sourceNode: s, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
WITH last(nodes(path)) AS n, length(path) AS h, reduce(c = 1.0, r IN relationships(path) | CASE WHEN r.cap < c THEN r.cap ELSE c END) AS bottleneck
WITH n, min(h) AS hops, max(bottleneck) AS max_cap
RETURN n.id AS id, hops, max_cap, n.tier AS tier
ORDER BY hops, id
LIMIT 100
