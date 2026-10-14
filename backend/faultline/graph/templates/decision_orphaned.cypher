// id: Q-DEC-ORPHAN
// purpose: knowledge health (M17): active decisions whose deciders have all left (every Person who DECIDED it is inactive), so nobody who made the call is around to explain it
// seen: decision
MATCH (p:Person)-[:DECIDED]->(d:Decision {status: 'active'})
WITH d, collect(p) AS deciders
WHERE size(deciders) > 0 AND all(x IN deciders WHERE coalesce(x.active, false) = false)
RETURN d.id AS decision, d.title AS title, d.decided_at AS decided_at, d.url AS url,
       [x IN deciders | x.id] AS deciders, [(d)-[:CONSTRAINS]->(n) | n.id] AS constrains
ORDER BY decided_at, decision
LIMIT 25
