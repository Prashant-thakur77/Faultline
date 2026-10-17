// id: Q-VEC-ANN
// purpose: the vector index top 10 on one label for an embedding (evals/vector_recall.py: recall@10 of the HNSW index against the exact scan Q-VEC-EXACT)
// seen: id
CALL db.idx.vector.queryNodes($label, 'embedding', 10, vecf32($q)) YIELD node, score
RETURN node.id AS id, score AS distance
ORDER BY distance, id
LIMIT 10
