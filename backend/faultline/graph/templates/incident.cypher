// id: Q-INC-1
// purpose: an incident, its stage, onset and symptoms (targets)
// returns: single-row
// seen: id, targets
MATCH (i:Incident {id:$inc})
OPTIONAL MATCH (i)-[:HAS_SYMPTOM]->(s:Symptom)
RETURN i.id AS id, i.title AS title, i.stage AS stage, i.onset_at AS onset_at, i.opened_at AS opened_at,
       i.confident AS confident, collect(DISTINCT s.target_id) AS targets, collect(DISTINCT s.kind) AS kinds
LIMIT 1
