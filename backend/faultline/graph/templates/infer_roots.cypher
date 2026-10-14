// id: Q-INFER-1
// purpose: abstention path: among MEASURED-anomalous nodes, the upstream-most ones (no anomalous dependency of their own) that no change in the window touched: the inferred, unconfirmed origin
// seen: id
MATCH (a:Node) WHERE a.id IN $anomalous AND NOT a.id IN $symptoms
WITH a, size([(a)-[:DEPENDS_ON*1..6]->(b:Node) WHERE b.id IN $anomalous | b]) AS anomalous_upstream,
     size([(d:Deploy)-[:CHANGED]->(a) WHERE d.at >= $since | d]) AS recent_changes
WHERE anomalous_upstream = 0 AND recent_changes = 0
RETURN a.id AS id, [x IN labels(a) WHERE x <> 'Node'][0] AS label, a.tier AS tier
ORDER BY id
LIMIT 10
