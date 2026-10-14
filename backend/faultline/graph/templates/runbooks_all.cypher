// id: Q-MEM-RB
// purpose: procedural memory overview (Memory tab): every runbook in effect, derived ones first by support, with what it covers and the postmortems it was DERIVED_FROM
// seen: id, for_ids
MATCH (r:Runbook)
WHERE r.valid_to IS NULL
RETURN r.id AS id, r.title AS title, r.source AS source, coalesce(r.support_count, 0) AS support,
       coalesce(r.salience, 1.0) AS salience, r.reviewed_at AS reviewed_at,
       [(r)-[:RUNBOOK_FOR]->(x:Node) | x.id] AS for_ids,
       [(r)-[:DERIVED_FROM]->(pm:Postmortem) | pm.id] AS derived_from
ORDER BY CASE source WHEN 'derived' THEN 0 ELSE 1 END, support DESC, id
LIMIT 50
