// id: Q-ORG-HARM
// purpose: who fixes it: algo.HarmonicCentrality over the symmetric KNOWS_ABOUT scratch projection (people close to the cause's code, incidents and on-call); people only, ranked before the LIMIT, so files and incidents in the projection never push a person out of the top 50 (a top-k read: who_fixes shows 10)
// seen: id
CALL {algo:harmonic}({nodeLabels: ['Node'], relationshipTypes: ['KNOWS_ABOUT']}) YIELD node, score, reachable
WITH node, score, reachable
WHERE node.kind = 'person'
RETURN node.id AS id, node.kind AS kind, score, reachable
ORDER BY score DESC, id
LIMIT 50
