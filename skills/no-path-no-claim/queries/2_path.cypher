// G2, no path no claim: the shortest causal paths from the change to the symptom. No row = the change cannot be claimed.
// Params: $change, $symptom.
MATCH (c:Node {id: $change}), (s:Node {id: $symptom})
CALL algo.SPpaths({sourceNode: c, targetNode: s, relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w',
                   relDirection: 'outgoing', maxLen: 8, pathCount: 3}) YIELD path, pathWeight
RETURN [n IN nodes(path) | n.id] AS chain, length(path) AS hops
ORDER BY pathWeight, hops
LIMIT 3
