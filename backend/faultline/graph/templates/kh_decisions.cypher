// id: Q-KH-3
// purpose: knowledge health, decisions: active decisions whose constrained components changed owner after the decision (the deciding team may be gone), and how often incident causes have violated them
// seen: decision, owner_changed_since
// (the relationship is named so parallel VIOLATES edges count once each: anonymous ones collapse; docs/upstream/12)
MATCH (d:Decision)-[:CONSTRAINS]->(n:Node)<-[o:OWNED_AT]-(t:Team)
WHERE d.status = 'active' AND o.to IS NULL
WITH d, collect({c: n.id, since: o.from}) AS scope
WITH d, [x IN scope WHERE x.since > d.decided_at | x.c] AS owner_changed_since,
     size([(c:Node)-[v:VIOLATES]->(d) | v.k]) AS violations
WHERE size(owner_changed_since) > 0 OR violations > 0
RETURN d.id AS decision, d.title AS title, d.decided_at AS decided_at, owner_changed_since, violations
ORDER BY violations DESC, size(owner_changed_since) DESC, decision
LIMIT 50
