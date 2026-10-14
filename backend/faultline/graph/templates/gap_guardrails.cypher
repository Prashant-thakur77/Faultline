// id: Q-GAP-1
// purpose: missing guardrails (set difference): revenue-path services with no owning team or no current runbook
// seen: id
MATCH (s:Service)
WHERE s.revenue_path = true
WITH s, size([(t:Team)-[:OWNS]->(s) | t]) AS owners, size([(r:Runbook)-[:RUNBOOK_FOR]->(s) WHERE r.valid_to IS NULL | r]) AS runbooks
WHERE owners = 0 OR runbooks = 0
RETURN s.id AS id, s.name AS name, owners = 0 AS no_owner, runbooks = 0 AS no_runbook, s.tier AS tier
ORDER BY tier, id
LIMIT 50
