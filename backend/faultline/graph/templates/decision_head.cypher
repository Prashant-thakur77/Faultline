// id: Q-DEC-2
// purpose: trace a decision to its current head through SUPERSEDES (newest active descendant)
// returns: single-row
// seen: id, head
MATCH (d:Decision {id:$id})
OPTIONAL MATCH h=(d)<-[:SUPERSEDES*1..10]-(newer:Decision)
RETURN d.id AS id, d.status AS status, coalesce(newer.id, d.id) AS head, coalesce(length(h), 0) AS depth
ORDER BY depth DESC
LIMIT 1
