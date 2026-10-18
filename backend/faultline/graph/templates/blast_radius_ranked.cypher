// id: Q-BLAST-3
// purpose: blast radius ranked inside the engine: algo.BFS reach, algo.SSpaths hop distance and bottleneck cap, scored by the faultline.impact UDF (tier weight × 1/(1+hops) × ln(1+traffic+1); $tw = weights.yaml impact.tier_weight)
// seen: id
// (SSpaths is aggregated per node inside its own subquery first: FalkorDB 6.0.2 panics on SSpaths + aggregation grouped with a null property; docs/upstream/08)
MATCH (s:Node {id:$id})
CALL {
  WITH s
  CALL {algo:sspaths}({sourceNode: s, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
  WITH last(nodes(path)) AS n, length(path) AS h, reduce(c = 1.0, r IN relationships(path) | CASE WHEN r.cap < c THEN r.cap ELSE c END) AS bottleneck
  WITH n, min(h) AS hops, max(bottleneck) AS max_cap
  RETURN collect({id: n.id, hops: hops, max_cap: max_cap}) AS reach_hops
}
CALL {algo:bfs}(s, 8, 'PROPAGATES_TO') YIELD nodes
UNWIND nodes AS n
WITH n, [x IN reach_hops WHERE x.id = n.id][0] AS h
WITH n, h.hops AS hops, h.max_cap AS max_cap
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, n.tier AS tier, n.revenue_path AS revenue,
       hops, max_cap, faultline.round4(faultline.impact($tw, n.tier, hops, coalesce(max_cap, 0.0) * 100)) AS impact
ORDER BY impact DESC, id
LIMIT 100
