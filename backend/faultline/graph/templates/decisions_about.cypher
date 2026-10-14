// id: Q-DEC-ABOUT
// purpose: company brain: every decision that constrains a component, with what superseded it (current = active and not superseded)
// seen: id, superseded_by
MATCH (d:Decision)-[:CONSTRAINS]->(x:Node {id:$id})
RETURN d.id AS id, d.title AS title, d.status AS status, d.decided_at AS decided_at, d.url AS url,
       [(d)<-[:SUPERSEDES]-(n:Decision) | n.id] AS superseded_by
ORDER BY status, id
LIMIT 20
