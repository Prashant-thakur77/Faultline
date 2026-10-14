// id: Q-CUT-2
// purpose: candidate cut edges with capacities: ALL PROPAGATES_TO edges inside the region reachable from $failing (zero-flow included, for residual reachability)
// seen: u, v
MATCH (f:Node {id:$failing})
CALL {algo:sspaths}({sourceNode: f, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
WITH f, collect(DISTINCT last(nodes(path))) + [f] AS region
UNWIND region AS a
MATCH (a)-[r:PROPAGATES_TO]->(b)
WHERE b IN region
RETURN a.id AS u, b.id AS v, r.cut_cost AS cut_cost, r.cap AS cap, r.domain AS domain
ORDER BY u, v
LIMIT 100
