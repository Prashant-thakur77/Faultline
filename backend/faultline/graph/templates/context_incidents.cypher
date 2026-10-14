// id: Q-CTX-INC
// purpose: context pack (M16.1), what happened last time: for past incidents found by meaning, the title, the change that CAUSED it and the component it changed, the action that RESOLVED it and its verdict, and who resolved it (episodic memory an agent can act on, not a bare id)
// seen: id, cause, cause_target, fix_target, resolvers
MATCH (i:Incident) WHERE i.id IN $ids
WITH i, [(d:Deploy)-[:CAUSED]->(i) | d] AS ds, [(i)-[:RESOLVED_BY]->(a:Action) | a] AS acts,
     [(p:Person)-[:RESOLVED]->(i) | p.id] AS resolvers
WITH i, resolvers, CASE WHEN size(ds) > 0 THEN ds[0] ELSE null END AS d, CASE WHEN size(acts) > 0 THEN acts[0] ELSE null END AS a
RETURN i.id AS id, i.title AS title, i.opened_at AS opened_at, i.onset_at AS onset_at, d.id AS cause, CASE WHEN d IS NULL THEN null ELSE [(d)-[:CHANGED]->(x:Node) | x.id][0] END AS cause_target,
       a.kind AS fix_kind, a.target_id AS fix_target, a.verdict AS fix_verdict, resolvers
ORDER BY id
LIMIT 20
