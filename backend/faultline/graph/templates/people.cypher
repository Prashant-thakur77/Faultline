// id: Q-ORG-PEOPLE
// purpose: names, teams and activity of a set of people (for reasons shown to humans)
// seen: id
MATCH (p:Person) WHERE p.id IN $ids
RETURN p.id AS id, p.name AS name, p.active AS active, p.role AS role,
       [(p)-[:MEMBER_OF]->(t:Team) | t.id] AS teams
ORDER BY id
LIMIT 100
