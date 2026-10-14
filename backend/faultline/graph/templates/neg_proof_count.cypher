// id: Q-NEG-2
// purpose: completeness check for Q-NEG-1: how many paths each window change returned (= path_count ⇒ possibly truncated ⇒ UNKNOWN)
// seen: change
MATCH (d:Deploy) WHERE d.at >= $now - $window_ms AND d.at <= $now
CALL {algo:sspaths}({sourceNode: d, relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
RETURN d.id AS change, count(path) AS paths
ORDER BY change
LIMIT 50
