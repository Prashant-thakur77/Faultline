// id: Q-OWN-MAP
// purpose: company brain ownership map: every team with the components it owns now (OWNS) and its active members (ownership history per component: Q-OWN-AT)
// seen: team, owns
MATCH (t:Team)
WITH t, [(t)-[:OWNS]->(c:Node) | c.id] AS owns
WHERE size(owns) > 0
RETURN t.id AS team, t.name AS name, owns, size(owns) AS n_owned,
       size([(p:Person)-[:MEMBER_OF]->(t) WHERE p.active = true | p]) AS active_members
ORDER BY n_owned DESC, team
LIMIT 100
