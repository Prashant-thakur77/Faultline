// id: Q-RANK-1
// purpose: algorithmic cause ranking: algo.pageRank over DEPENDS_ON in the incident's scratch projection (mass flows to upstream nodes many symptoms depend on)
// seen: id
CALL {algo:pagerank}('Node', 'DEPENDS_ON') YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC, id
LIMIT 50
