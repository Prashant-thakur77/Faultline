// id: Q-COL-1
// purpose: column lineage chains for a field (DERIVES_FROM, bounded)
// seen: chain
MATCH p=(c:Column {id:$column})-[:DERIVES_FROM*1..6]->(up:Column)
RETURN c.id AS column, [n IN nodes(p) | n.id] AS chain, length(p) AS hops
ORDER BY hops DESC, column
LIMIT 50
