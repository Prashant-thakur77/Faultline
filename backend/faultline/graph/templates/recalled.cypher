// id: Q-MEM-4
// purpose: what an incident recalled at RECALL (the RECALLED edges written then): similarity, recency, salience and the fixes that worked
// seen: id
MATCH (cur:Incident {id:$inc})-[r:RECALLED]->(p:Incident)
RETURN p.id AS id, p.title AS title, r.similarity AS similarity, r.recency AS recency, r.salience AS salience,
       r.shared AS shared,
       [(p)-[:RESOLVED_BY|ATTEMPTED]->(a:Action) | {kind: a.kind, verdict: a.verdict, target: a.target_id}] AS actions,
       [(t:Node)<-[:CHANGED]-(:Deploy)-[:CAUSED]->(p) | t.id] AS cause_targets
ORDER BY similarity DESC, id
LIMIT 10
