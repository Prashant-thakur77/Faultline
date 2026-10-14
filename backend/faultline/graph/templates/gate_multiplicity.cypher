// id: Q-GATE-MULT
// purpose: G5 multiplicity per suspect: how many distinct failure paths (up to 100, algo.SPpaths) lead from each source to the symptom. A request can meet the same fault once per path, so a source's sound G5 bound is min(1, k × maxFlow); k = 1 leaves it unchanged (gate bench / G5 property finding)
// seen: source
MATCH (t:Node {id: $symptom})
UNWIND $sources AS sid
MATCH (s:Node {id: sid})
CALL {algo:sppaths}({sourceNode: s, targetNode: t, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 100}) YIELD path
RETURN s.id AS source, count(path) AS paths
ORDER BY source
LIMIT 100
