// id: Q-GATE-1
// purpose: THE load-bearing query (gate G2): shortest causal paths cause → symptom. Empty = no path, no claim. learned_from names, per hop, the incident whose verified fix taught a learned link ('' for an ordinary edge), so a proof that relies on one says so

// seen: chain
MATCH (c:Node {id:$cause}), (s:Node {id:$symptom})
CALL {algo:sppaths}({sourceNode: c, targetNode: s, relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 3}) YIELD path, pathWeight
RETURN [n IN nodes(path) | n.id] AS chain, [r IN relationships(path) | type(r)] AS rels, pathWeight AS weight, length(path) AS hops,
       [r IN relationships(path) | coalesce(r.from_incident, '')] AS learned_from
ORDER BY weight, hops
LIMIT 3
