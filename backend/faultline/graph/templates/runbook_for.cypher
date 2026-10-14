// id: Q-MEM-3
// purpose: procedural memory first: current runbooks for the given components/symptoms (derived ones before human ones, then by support)
// seen: id
MATCH (r:Runbook)-[:RUNBOOK_FOR]->(x:Node)
WHERE x.id IN $ids AND r.valid_to IS NULL
WITH r, collect(DISTINCT x.id) AS for_ids
RETURN r.id AS id, r.title AS title, r.source AS source, coalesce(r.salience, 1.0) AS salience,
       coalesce(r.support_count, 0) AS support, r.steps AS steps, for_ids,
       [(r)-[:DERIVED_FROM]->(pm:Postmortem) | pm.id] AS derived_from
ORDER BY CASE r.source WHEN 'derived' THEN 0 ELSE 1 END, support DESC, salience DESC, id
LIMIT 10
