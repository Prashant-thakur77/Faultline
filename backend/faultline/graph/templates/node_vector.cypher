// id: Q-VEC-1
// purpose: a node's stored embedding (forget proof: re-query the index with it after deletion)
// returns: single-row
// seen: id
MATCH (n:Node {id:$id})
RETURN n.id AS id, n.embedding AS embedding
LIMIT 1
