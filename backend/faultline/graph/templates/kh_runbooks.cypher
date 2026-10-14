// id: Q-KH-1
// purpose: knowledge health, runbooks: human runbooks in effect that are stale (not reviewed for $stale_days) or that predate the current owning team (written by the previous owner)
// seen: component, runbook, owner
MATCH (r:Runbook)-[:RUNBOOK_FOR]->(n:Node)<-[o:OWNED_AT]-(t:Team)
WHERE o.to IS NULL AND r.reviewed_at IS NOT NULL AND r.valid_to IS NULL
WITH n, r, t, o, toInteger(($now - r.reviewed_at) / 86400000) AS age_days
WHERE age_days >= $stale_days OR r.reviewed_at < o.from
RETURN n.id AS component, n.tier AS tier, r.id AS runbook, age_days, r.reviewed_at < o.from AS predates_owner,
       t.id AS owner, o.from AS owner_since
ORDER BY coalesce(n.tier, 9), age_days DESC, runbook
LIMIT 50
