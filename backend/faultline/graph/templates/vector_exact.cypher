// id: Q-VEC-EXACT
// purpose: the exact top 10 by cosine distance over every node of one label, a full scan (the ground truth for Q-VEC-ANN recall; evals only)
// seen: id
MATCH (n:Node)
WHERE $label IN labels(n) AND n.embedding IS NOT NULL
WITH n, vec.cosineDistance(n.embedding, vecf32($q)) AS distance
RETURN n.id AS id, distance
ORDER BY distance, id
LIMIT 10
