// id: Q-LIN-1
// (aggregate per node first, then project: FalkorDB 6.0.2 panics on SSpaths + aggregation grouped with a null property; docs/upstream/08)
// purpose: upstream scope of a symptom (everything it depends on, with hop distance) (algo.SSpaths over DEPENDS_ON)
// seen: id
MATCH (sym:Node {id:$symptom})
CALL {algo:sspaths}({sourceNode: sym, relTypes: ['DEPENDS_ON'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
WITH last(nodes(path)) AS n, min(length(path)) AS hops
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, hops
ORDER BY hops, id
LIMIT 100
