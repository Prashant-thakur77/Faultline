// id: Q-CTX-1
// purpose: context of any target: owner team, current on-call, runbooks, active decisions
// returns: single-row
// seen: id, team, oncall, runbooks, decisions
MATCH (s:Node {id:$id})
OPTIONAL MATCH (t:Team)-[:OWNS]->(s)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t)
WHERE oc.from <= $now AND $now < oc.to AND p.active // lint: optional-where-ok (filters the optional on-call match)
OPTIONAL MATCH (r:Runbook)-[:RUNBOOK_FOR]->(s)
WHERE r.valid_to IS NULL // lint: optional-where-ok
OPTIONAL MATCH (d:Decision {status:'active'})-[:CONSTRAINS]->(s)
RETURN s.id AS id, [x IN labels(s) WHERE x <> 'Node'][0] AS label, t.id AS team,
       collect(DISTINCT p.id) AS oncall, collect(DISTINCT r.id) AS runbooks, collect(DISTINCT d.id) AS decisions
LIMIT 1
