// id: Q-ASOF-1
// purpose: what the graph believed about a component at time $at: owning team, on-call person, decisions in force (decided by then and not yet superseded) and runbooks in effect
// returns: single-row
// seen: owner, oncall, decisions, runbooks
// (outer list filters: a comprehension naming a relationship variable empties later ones; docs/upstream/09)
MATCH (n:Node {id: $id})
WITH n, [x IN [(t:Team)-[o:OWNED_AT]->(n) | {team: t.id, from: o.from, to: o.to}] WHERE x.from <= $at AND (x.to IS NULL OR $at < x.to) | x.team] AS owner
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t:Team)
WHERE t.id IN owner AND oc.from <= $at AND $at < oc.to   // lint: optional-where-ok (anchored on the owner, docs/upstream/10)
WITH n, owner, collect(DISTINCT p.id) AS oncall
WITH n, owner, oncall, [x IN [(d:Decision)-[:CONSTRAINS]->(n) | {id: d.id, at: d.decided_at, later: [(s:Decision)-[:SUPERSEDES]->(d) | s.decided_at]}] WHERE x.at <= $at AND size([y IN x.later WHERE y <= $at]) = 0 | x.id] AS decisions
RETURN n.id AS id, owner, oncall, decisions,
       [x IN [(r:Runbook)-[:RUNBOOK_FOR]->(n) | {id: r.id, from: coalesce(r.valid_from, r.reviewed_at), to: r.valid_to}] WHERE x.from <= $at AND (x.to IS NULL OR $at < x.to) | x.id] AS runbooks
LIMIT 1
