// id: Q-FORGET-1
// purpose: forget dry run (W-MEM-3 preview): nodes this Doc ALONE produced (deleted with it), their relationship counts and vectors
// seen: id
MATCH (:Doc {id:$doc})-[:PRODUCED]->(n)
MATCH (n)<-[:PRODUCED]-(d2:Doc)
WITH n, count(DISTINCT d2) AS producers
WHERE producers = 1
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, size([(n)-[r]-() | r]) AS rels,
       n.embedding IS NOT NULL AS has_vector
ORDER BY id
LIMIT 100
