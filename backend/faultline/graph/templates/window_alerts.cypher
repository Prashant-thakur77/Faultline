// id: Q-ALERT-1
// purpose: symptom alerts firing in a window that no incident holds yet (no DEGRADES edge), and what they fired on (INTAKE: the input of group_alerts); SLO-burn pages are budgets, not symptoms
// seen: id, target
MATCH (a:Alert)-[:FIRED_ON]->(x)
WHERE a.fired_at >= $since AND a.fired_at <= $until AND a.metric <> 'slo_burn' AND NOT (a)-[:DEGRADES]->(:Incident)
RETURN a.id AS id, x.id AS target, a.metric AS metric, a.fired_at AS fired_at, a.severity AS severity
ORDER BY fired_at, id
LIMIT 50
