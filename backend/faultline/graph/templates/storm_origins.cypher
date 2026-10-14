// id: Q-STORM-ORIGINS
// purpose: attach-or-open (INTAKE): every OPEN incident (stage not terminal and not resolved: a verified write-back sets resolved_at) with a gate-confirmed cause, and the component that cause changed (its confirmed origin)
// seen: incident, origin
// (confirmed only: the origin of an open NOT_CONFIDENT incident is unproven and does not absorb alerts; agent/intake.py says why)
MATCH (i:Incident)-[:HYPOTHESIZES]->(h:Hypothesis {status: 'confirmed'})-[:BLAMES]->(c:Node)-[:CHANGED|GATES]->(o:Node)
WHERE NOT i.stage IN $terminal AND i.resolved_at IS NULL
RETURN i.id AS incident, c.id AS cause, o.id AS origin
ORDER BY incident, origin
LIMIT 50
