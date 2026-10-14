// id: Q-MEM-8
// purpose: family prior for HYPOTHESIZE: per component, the strongest recalled precedent whose cause changed it (max similarity × recency over the RECALLED edges)
// seen: target
MATCH (cur:Incident {id:$inc})-[r:RECALLED]->(p:Incident)
MATCH (t:Node)<-[:CHANGED]-(:Deploy)-[:CAUSED]->(p)
RETURN t.id AS target, max(r.similarity * r.recency) AS prior, collect(DISTINCT p.id) AS precedents
ORDER BY prior DESC, target
LIMIT 20
