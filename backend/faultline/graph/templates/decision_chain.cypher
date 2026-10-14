// id: Q-DEC-CHAIN
// purpose: decision tracer: the whole SUPERSEDES chain a decision belongs to (older and newer, ≤ 10 hops each way), oldest first, with what each one replaced
// seen: id
MATCH (d:Decision {id:$id})
MATCH (d)-[:SUPERSEDES*0..10]-(n:Decision)
WITH DISTINCT n
RETURN n.id AS id, n.title AS title, n.status AS status, n.decided_at AS decided_at, n.url AS url,
       [(n)-[:SUPERSEDES]->(old:Decision) | old.id] AS supersedes,
       [(newer:Decision)-[:SUPERSEDES]->(n) | newer.id] AS superseded_by
ORDER BY decided_at, id
LIMIT 25
