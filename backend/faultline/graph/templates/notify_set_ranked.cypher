// id: Q-NOTIFY-2
// purpose: who to NOTIFY (not who fixes), ranked inside the engine: algo.SSpaths blast radius of $id (hops, bottleneck cap), the teams owning each impacted node, their summed faultline.capImpact (tier weight × cap / (1+hops); $tw = weights.yaml impact.tier_weight), the nearest hop, the $priority nodes they own and who is on call for them at $now
// seen: team, owns_impacted, oncall
// (nested filter: FalkorDB 6.0.2 returns [] for a comprehension mixing relationship- and node-variable predicates after an aggregating WITH; docs/upstream/11)
MATCH (s:Node {id:$id})
CALL {algo:sspaths}({sourceNode: s, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
WITH last(nodes(path)) AS n, length(path) AS h, reduce(c = 1.0, r IN relationships(path) | CASE WHEN r.cap < c THEN r.cap ELSE c END) AS bottleneck
WITH n, min(h) AS hops, max(bottleneck) AS max_cap
WHERE n.id <> $id
MATCH (t:Team)-[:OWNS]->(n)
WITH DISTINCT t, n, hops, max_cap
WITH t, collect(n.id) AS owns_impacted, sum(faultline.capImpact($tw, n.tier, max_cap, hops)) AS impact, min(hops) AS nearest_hops
WITH t, owns_impacted, faultline.round4(impact) AS impact, nearest_hops, [x IN owns_impacted WHERE x IN $priority] AS priority
RETURN t.id AS team, t.name AS name, owns_impacted,
       [x IN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND $now < oc.to | p] WHERE x.active | x.id] AS oncall,
       impact, nearest_hops, priority
ORDER BY CASE WHEN size(priority) > 0 THEN 0 ELSE 1 END, impact DESC, team
LIMIT 20
