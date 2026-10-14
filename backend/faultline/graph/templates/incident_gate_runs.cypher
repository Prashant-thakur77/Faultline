// id: Q-INC-GATES
// purpose: every gate run of an incident, in order (rejections are first-class; UI checklist + replay export)
// seen: cause
MATCH (i:Incident {id:$inc})-[:HAS_GATE_RUN]->(g:GateRun)
RETURN g.id AS id, g.cause_id AS cause, g.passed AS passed, g.confident AS confident, g.checks AS checks,
       g.attempt AS attempt, g.origin AS origin, g.at AS at
ORDER BY at, id
LIMIT 100
