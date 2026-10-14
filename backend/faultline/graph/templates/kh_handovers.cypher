// id: Q-KH-2
// purpose: knowledge health, handovers: components that changed owning team with no runbook reviewed since the handover; the previous team's people who worked on it are who to ask
// seen: component, owner, previous_owner, ask
MATCH (prev:Team)-[po:OWNED_AT]->(n:Node)<-[o:OWNED_AT]-(t:Team)
WHERE o.to IS NULL AND po.to = o.from AND prev.id <> t.id
WITH n, t, o, prev
WITH n, t, o, prev, [(r:Runbook)-[:RUNBOOK_FOR]->(n) WHERE r.reviewed_at >= o.from | r.id] AS reviewed_since
WHERE size(reviewed_since) = 0
RETURN n.id AS component, n.tier AS tier, t.id AS owner, o.from AS handed_over_at, prev.id AS previous_owner,
       [(p:Person)-[:MEMBER_OF]->(prev) WHERE p.active AND (p)-[:COMMITTED]->(n) | p.id] AS ask,
       size([(r2:Runbook)-[:RUNBOOK_FOR]->(n) | r2]) AS runbooks
ORDER BY coalesce(n.tier, 9), handed_over_at DESC, component
LIMIT 50
