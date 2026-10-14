// id: Q-GATE-3
// purpose: gate G5 sufficiency bound: max share of the symptom that the source set can explain (single or joint)
// returns: single-row
// (no rows when no source node exists: callers treat that as zero flow, never as a pass)
MATCH (s:Node) WHERE s.id IN $sources
WITH collect(s) AS srcs
WHERE size(srcs) > 0
MATCH (t:Node {id:$symptom})
CALL {algo:maxflow}({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow
RETURN maxFlow AS max_flow, size(srcs) AS sources
LIMIT 1
