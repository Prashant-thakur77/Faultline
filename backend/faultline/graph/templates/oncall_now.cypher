// id: Q-ONCALL-NOW
// purpose: who is on call at $now: every team, with the active person whose ON_CALL shift covers $now and the shift window (person null when nobody covers the team)
// seen: team, person
MATCH (t:Team)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t)
WHERE oc.from <= $now AND $now < oc.to AND p.active // lint: optional-where-ok
RETURN t.id AS team, t.name AS team_name, p.id AS person, p.name AS name, oc.from AS from, oc.to AS to
ORDER BY team, person
LIMIT 100
