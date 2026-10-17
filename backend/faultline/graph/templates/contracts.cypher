// id: Q-CONTRACTS
// purpose: the standing approvals (Contract) of this tenant, newest grant first: scope, who granted it, what it COVERS, its uses (ContractUse nodes) and its status at $now (an active contract past expires_at reads expired)
// home: oncall
// seen: id, granted_by
MATCH (c:Contract)-[:GRANTED_BY]->(p:Person)
WHERE c.status <> 'offered'
OPTIONAL MATCH (c)-[:COVERS]->(n:Node)
WITH c, p, n, [(c)-[:USED_IN]->(u:ContractUse) | {id: u.id, incident: u.incident, at: u.at, verdict: u.verdict, graph: u.graph, action: u.action}] AS used_in
RETURN c.id AS id, c.family AS family, c.action_kind AS action_kind, c.params_hash AS params_hash, c.params AS params,
       c.max_uses AS max_uses, c.uses AS uses, c.days AS days, c.expires_at AS expires_at, c.granted_at AS granted_at,
       CASE WHEN c.status = 'active' AND c.expires_at <= $now THEN 'expired' ELSE c.status END AS status,
       c.quote AS quote, p.id AS granted_by, p.name AS granted_by_name, n.id AS covers, c.source_incident AS source_incident,
       c.revoked_at AS revoked_at, c.revoked_by AS revoked_by, used_in
ORDER BY granted_at DESC, id
LIMIT 100
