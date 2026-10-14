// id: Q-INC-ALERTS
// purpose: the alerts an incident holds (DEGRADES): INTAKE opened it with them or a later alert attached to it, how, at what hop distance from the confirmed origin, and on which group_alerts evidence
// seen: alert, target
MATCH (a:Alert)-[d:DEGRADES]->(i:Incident {id: $inc})
MATCH (a)-[:FIRED_ON]->(t:Node)
RETURN a.id AS alert, t.id AS target, a.metric AS metric, a.fired_at AS fired_at, d.how AS how, d.hops AS hops, d.evidence AS evidence
ORDER BY fired_at, alert
LIMIT 100
