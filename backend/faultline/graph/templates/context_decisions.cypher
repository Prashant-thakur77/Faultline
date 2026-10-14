// id: Q-CTX-DEC
// purpose: context pack (M16.1): the decisions in force at $now that constrain any of the given components, in one query (was one Q-DEC-ABOUT per component), ordered by the caller's component order ($ids: nearest first): active, not superseded, decided at or before $now (as of the pack's time)
// seen: id, component
UNWIND range(0, size($ids) - 1) AS j
WITH j, $ids[j] AS cid
MATCH (d:Decision)-[:CONSTRAINS]->(n:Node)
WHERE n.id = cid AND d.status = 'active' AND (d.decided_at IS NULL OR d.decided_at <= $now)
  AND NOT (d)<-[:SUPERSEDES]-(:Decision)
RETURN j AS position, cid AS component, d.id AS id, d.title AS title, d.decided_at AS decided_at
ORDER BY position, id
LIMIT 100
