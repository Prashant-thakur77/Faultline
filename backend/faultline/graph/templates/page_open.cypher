// id: Q-PAGE-OPEN
// purpose: pages a human still has to acknowledge (status sent or delivery_failed, kind page or escalation), oldest deadline first, with the person paged, the incident and whether the ack deadline has passed at $now
// home: oncall
// seen: id, incident, person
MATCH (pg:Page)-[:PAGES]->(p:Person)
WHERE pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation']
RETURN pg.id AS id, pg.incident AS incident, pg.kind AS kind, pg.urgency AS urgency, pg.status AS status,
       pg.attempt AS attempt, pg.sent_at AS sent_at, pg.ack_due_at AS ack_due_at, p.id AS person, p.name AS person_name,
       pg.ack_due_at <= $now AS overdue
ORDER BY ack_due_at, id
LIMIT 100
