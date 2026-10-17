// id: Q-PAGES
// purpose: the pager inbox of one graph, newest first: every Page (optionally of one incident, optionally with some statuses) with the person it PAGES, its incident title and stage, who acked it and the page it ESCALATED_TO; overdue (unacked past ack_due_at at $now) is decided here
// home: oncall
// seen: id, incident, person
MATCH (pg:Page)-[:PAGES]->(p:Person)
WHERE ($incident = '' OR pg.incident = $incident) AND (size($statuses) = 0 OR pg.status IN $statuses)
OPTIONAL MATCH (pg)-[:FOR]->(i:Incident)
OPTIONAL MATCH (pg)-[:ESCALATED_TO]->(nx:Page)
OPTIONAL MATCH (a:Person)-[:ACKED]->(pg)
RETURN pg.id AS id, pg.incident AS incident, i.title AS incident_title, i.stage AS incident_stage, pg.kind AS kind,
       pg.channel AS channel, pg.channels AS channels, pg.urgency AS urgency, pg.sent_at AS sent_at,
       pg.ack_due_at AS ack_due_at, pg.status AS status, pg.attempt AS attempt, pg.detail AS detail,
       pg.reason AS reason, pg.team AS team, pg.delivery AS delivery, pg.deep_link AS deep_link,
       p.id AS person, p.name AS person_name, a.id AS acked_by, a.name AS acked_by_name, pg.acked_at AS acked_at,
       pg.ack_via AS ack_via, pg.ack_actor AS ack_actor, nx.id AS escalated_to, pg.settled_at AS settled_at,
       pg.escalated_at AS escalated_at,
       pg.status IN ['sent', 'delivery_failed'] AND pg.kind IN ['page', 'escalation'] AND pg.ack_due_at <= $now AS overdue
ORDER BY sent_at DESC, id
LIMIT 100
