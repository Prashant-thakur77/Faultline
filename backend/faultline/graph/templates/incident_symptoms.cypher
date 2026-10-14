// id: Q-INC-SYM
// purpose: the Symptom nodes of an incident
// seen: id
MATCH (i:Incident {id:$inc})-[:HAS_SYMPTOM]->(s:Symptom)
RETURN s.id AS id, s.kind AS kind, s.target_id AS target
ORDER BY id
LIMIT 20
