// id: Q-PAGE-OVERDUE
// purpose: escalation input: pages nobody acknowledged by their deadline (status sent or delivery_failed, kind page or escalation, or a contract notice whose fix never settled, ack_due_at at or before $now) whose incident is not settled ($settled stages) and has no page acked that was sent at or after them (an earlier wave acknowledged does not silence a later one, e.g. a page after an approval), oldest deadline first
// home: oncall
// seen: page, incident, person
MATCH (pg:Page)-[:FOR]->(i:Incident)
WHERE pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation', 'contract_notice']
  AND pg.ack_due_at <= $now
  AND NOT i.stage IN $settled
WITH pg, i, [(i)<-[:FOR]-(o:Page) WHERE o.status = 'acked' AND o.sent_at >= pg.sent_at | o.id] AS acked
WHERE size(acked) = 0
MATCH (pg)-[:PAGES]->(p:Person)
RETURN pg.id AS page, i.id AS incident, p.id AS person, pg.attempt AS attempt, pg.urgency AS urgency,
       pg.ack_due_at AS due, pg.kind AS kind
ORDER BY due, page
LIMIT 50
