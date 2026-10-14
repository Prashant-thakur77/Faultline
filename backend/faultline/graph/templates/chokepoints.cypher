// id: Q-CHOKE-1
// purpose: chokepoints: betweenness over service calls (seeded sampling → identical every run)
// seen: id
CALL {algo:betweenness}({nodeLabels: ['Service', 'Datastore'], relationshipTypes: ['CALLS'], samplingSize: 64, samplingSeed: 42}) YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC, id
LIMIT 10
