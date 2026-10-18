// id: Q-RUNBOOK-ABOUT
// purpose: which runbook to follow for a component: the current runbooks written for it or for one of its symptoms (Symptom.target_id), then those for a component one failure hop away (what its failure reaches, or what reaches it); a runbook for a symptom kind the question names ranks first, derived runbooks (learned from fixes that worked) carry how often they worked
// seen: id, covers
MATCH (n:Node {id: $id})
WITH n, [(n)-[:PROPAGATES_TO]-(m:Node) | m.id] AS near
MATCH (r:Runbook)-[:RUNBOOK_FOR]->(x:Node)
WHERE r.valid_to IS NULL
  AND (x.id = n.id OR x.target_id = n.id OR x.id IN near OR x.target_id IN near)
WITH r, x, CASE WHEN x.id = n.id OR x.target_id = n.id THEN 0 ELSE 1 END AS dist,
     CASE WHEN x.kind IN $kinds THEN 1 ELSE 0 END AS named
WITH r, min(dist) AS dist, max(named) AS named, collect(DISTINCT x.id) AS covers
RETURN r.id AS id, r.title AS title, r.source AS source, dist, named = 1 AS symptom_named,
       coalesce(r.support_count, 0) AS worked, r.steps AS steps, r.reviewed_at AS reviewed_at, r.url AS url, covers
ORDER BY dist, named DESC, CASE r.source WHEN 'derived' THEN 0 ELSE 1 END, worked DESC, id
LIMIT 12
