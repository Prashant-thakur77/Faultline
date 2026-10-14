// id: Q-FIND-INCIDENT-VEC
// purpose: vector seed: nearest past incidents to a query embedding (score is a cosine distance; lower = closer)
// seen: id
CALL db.idx.vector.queryNodes('Incident', 'embedding', 10, vecf32($q)) YIELD node, score
RETURN node.id AS id, 'Incident' AS label, score AS distance, 1.0 - score AS similarity, 'vector' AS via
ORDER BY distance, id
LIMIT 10
