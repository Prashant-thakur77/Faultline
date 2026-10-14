// id: Q-RANK-SRC
// purpose: the dependency subgraph among the given nodes (projected into a scratch graph for algo.pageRank)
// seen: src, dst
MATCH (a:Node)-[r:DEPENDS_ON]->(b:Node)
WHERE a.id IN $ids AND b.id IN $ids
RETURN a.id AS src, b.id AS dst
ORDER BY src, dst
LIMIT 100
