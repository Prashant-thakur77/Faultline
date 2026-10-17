// id: Q-PAGE-ONE
// purpose: one page by id: the person it PAGES, its incident one-liner (title, stage, onset, report), who acked it and the page it ESCALATED_TO
// home: oncall
// returns: single-row
// seen: id, incident, person
MATCH (pg:Page {id:$page})-[:PAGES]->(p:Person)
OPTIONAL MATCH (pg)-[:FOR]->(i:Incident)
OPTIONAL MATCH (pg)-[:ESCALATED_TO]->(nx:Page)
OPTIONAL MATCH (a:Person)-[:ACKED]->(pg)
RETURN pg.id AS id, pg.incident AS incident, i.title AS incident_title, i.stage AS incident_stage,
       i.onset_at AS onset_at, i.report AS report, pg.kind AS kind, pg.channel AS channel, pg.channels AS channels,
       pg.urgency AS urgency, pg.sent_at AS sent_at, pg.ack_due_at AS ack_due_at, pg.status AS status,
       pg.attempt AS attempt, pg.detail AS detail, pg.reason AS reason, pg.team AS team, pg.delivery AS delivery,
       pg.deep_link AS deep_link, p.id AS person, p.name AS person_name, a.id AS acked_by, a.name AS acked_by_name,
       pg.acked_at AS acked_at, pg.ack_via AS ack_via, pg.ack_actor AS ack_actor, nx.id AS escalated_to,
       pg.settled_at AS settled_at, pg.escalated_at AS escalated_at, i.page_external AS external,
       pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation'] AND pg.ack_due_at <= $now AS overdue
LIMIT 1
