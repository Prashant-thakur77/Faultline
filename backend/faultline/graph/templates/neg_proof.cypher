// id: Q-NEG-1
// purpose: no-incident negative proof: anomalous nodes reachable from any change in the window (empty = none)
// seen: change, anomalous_reached
MATCH (d:Deploy) WHERE d.at >= $now - $window_ms AND d.at <= $now
CALL {algo:sspaths}({sourceNode: d, relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
WITH d, last(nodes(path)) AS reached
WHERE reached.id IN $anomalous_ids
WITH d, collect(DISTINCT reached.id) AS anomalous_reached, count(*) AS paths
RETURN d.id AS change, anomalous_reached, paths
ORDER BY change
LIMIT 50
