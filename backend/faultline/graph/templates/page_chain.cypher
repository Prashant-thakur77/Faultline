// id: Q-PAGE-CHAIN
// purpose: the escalation history of a page: every page of the same incident in the order it was sent, who it PAGES, its status, who acked it and the page it ESCALATED_TO
// home: oncall
// seen: id, person
MATCH (pg:Page {id:$page})-[:FOR]->(i:Incident)
MATCH (i)<-[:FOR]-(x:Page)-[:PAGES]->(p:Person)
OPTIONAL MATCH (x)-[:ESCALATED_TO]->(nx:Page)
RETURN x.id AS id, x.kind AS kind, p.id AS person, p.name AS person_name, x.status AS status, x.channel AS channel,
       x.urgency AS urgency, x.attempt AS attempt, x.sent_at AS sent_at, x.ack_due_at AS ack_due_at,
       x.acked_by AS acked_by, x.acked_at AS acked_at, x.ack_via AS ack_via, x.detail AS detail, nx.id AS escalated_to
ORDER BY sent_at, id
LIMIT 50
