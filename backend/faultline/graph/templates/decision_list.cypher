// id: Q-DEC-LIST
// purpose: company brain (decision tracer picker): every decision with its status, what it constrains and what supersedes it
// seen: id
MATCH (d:Decision)
RETURN d.id AS id, d.title AS title, d.status AS status, d.decided_at AS decided_at, d.url AS url,
       [(d)-[:CONSTRAINS]->(c:Node) | c.id] AS constrains,
       [(newer:Decision)-[:SUPERSEDES]->(d) | newer.id] AS superseded_by
ORDER BY decided_at, id
LIMIT 100
