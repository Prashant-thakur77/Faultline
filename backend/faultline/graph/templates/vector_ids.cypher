// id: Q-VEC-IDS
// purpose: the ids of the nodes of one label that carry an embedding, keyset-paged (evals/vector_recall.py takes its queries from them)
// seen: id
MATCH (n:Node)
WHERE $label IN labels(n) AND n.embedding IS NOT NULL AND n.id > $after
RETURN n.id AS id
ORDER BY id
LIMIT 100
