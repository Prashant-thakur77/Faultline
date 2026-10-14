// id: Q-SUS-1
// purpose: changes in the window on the symptom or anything upstream of it, with hop distance
// seen: deploy, target
// (the algorithm runs inside CALL { }: a symptom with nothing upstream yields no path rows, and without the subquery
//  the symptom itself (hops 0) would be dropped too, so a change ON it would never be proposed; gate bench finding)
// (scale benchmark finding: the deploys in the window are found first through the Deploy.at range index and then matched
//  against the upstream set. The earlier form, UNWIND ups … MATCH (d:Deploy)-[:CHANGED]->(x {id: u.id}), re-scanned
//  every CHANGED edge once per upstream path (paths × all deploys): 520 ms at 1k services, TIMEOUT at 10k. The
//  WITH ups, d between the two MATCH clauses is load-bearing: FalkorDB 6.0.2 drops the input of a WITH/UNWIND that
//  is followed by two MATCH clauses whose first is disconnected from it (docs/upstream/16)
MATCH (sym:Node {id:$symptom})
CALL { WITH sym CALL {algo:sspaths}({sourceNode: sym, relTypes: ['DEPENDS_ON'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
       RETURN collect({id: last(nodes(path)).id, hops: length(path)}) AS found }
WITH sym, found + [{id: sym.id, hops: 0}] AS ups
MATCH (d:Deploy) WHERE d.at >= $onset - $window_ms AND d.at <= $onset
WITH ups, d
MATCH (d)-[:CHANGED]->(x)
WITH d, x, [u IN ups WHERE u.id = x.id | u.hops] AS hs
WHERE size(hs) > 0
UNWIND hs AS h
WITH d, x, min(h) AS hops
RETURN d.id AS deploy, d.kind AS kind, x.id AS target, d.at AS at, hops
ORDER BY hops, at DESC, deploy
LIMIT 20
