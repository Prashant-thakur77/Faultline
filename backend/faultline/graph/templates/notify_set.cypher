// id: Q-NOTIFY-1
// purpose: who to NOTIFY (not who fixes): teams owning anything in the blast radius, the impacted nodes they own, and who is on call for them now
// seen: team, owns_impacted, oncall
// (nested filter: FalkorDB 6.0.2 returns [] for a comprehension mixing relationship- and node-variable predicates after an aggregating WITH; docs/upstream/11)
MATCH (t:Team)-[:OWNS]->(n:Node)
WHERE n.id IN $ids
WITH t, collect(DISTINCT n.id) AS owns_impacted
RETURN t.id AS team, t.name AS name, owns_impacted,
       [x IN [(p:Person)-[oc:ON_CALL]->(t) WHERE oc.from <= $now AND $now < oc.to | p] WHERE x.active | x.id] AS oncall
ORDER BY size(owns_impacted) DESC, team
LIMIT 20
