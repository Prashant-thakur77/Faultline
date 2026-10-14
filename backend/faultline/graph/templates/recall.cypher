// id: Q-MEM-1
// purpose: recall (recency = 0.5^(age/half-life), scenario clock via onset_at): vector seed (the incident's own embedding in the FalkorDB vector index) → structural confirmation (a shared Symptom node); returns what fixed it before
// seen: id, cause_targets
MATCH (cur:Incident {id:$current})
CALL db.idx.vector.queryNodes('Incident', 'embedding', 10, cur.embedding) YIELD node, score
WITH cur, node, score
WHERE node.id <> cur.id AND (node)-[:HAS_SYMPTOM]->(:Symptom)<-[:HAS_SYMPTOM]-(cur)
WITH cur, node, score, toFloat($now - coalesce(node.onset_at, node.opened_at)) AS age_ms
RETURN node.id AS id, node.title AS title, score AS distance, 1.0 - score AS similarity, node.salience AS salience,
       node.opened_at AS opened_at,
       CASE WHEN age_ms <= 0 THEN 1.0 ELSE exp(-0.6931471805599453 * age_ms / $half_life_ms) END AS recency,
       [(node)-[:HAS_SYMPTOM]->(sy:Symptom)<-[:HAS_SYMPTOM]-(cur) | sy.id] AS shared,
       [(node)-[:RESOLVED_BY]->(a:Action) WHERE a.verdict = 'APPLIED' | a.kind] AS fixes,
       [(t:Node)<-[:CHANGED]-(:Deploy)-[:CAUSED]->(node) | t.id] AS cause_targets,
       [(pm:Postmortem)-[:DOCUMENTS]->(node) | pm.summary] AS postmortem
ORDER BY distance, id
LIMIT 5
