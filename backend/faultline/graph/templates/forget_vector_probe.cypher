// id: Q-FORGET-2
// purpose: forget proof: re-query the vector index with a forgotten node's own vector; the node must not come back
// seen: id
CALL db.idx.vector.queryNodes($label, 'embedding', 5, vecf32($vec)) YIELD node, score
RETURN node.id AS id, score
ORDER BY score, id
LIMIT 5
