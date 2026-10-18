// id: Q-DEC-WHO
// purpose: who decided each of these decisions (by id), whether each person is still active, and whether each is still on a team that owns something the decision constrains; answers "who decided ADR-x, and are they still here?" for a decision found by its name or id rather than through a component
// seen: decision, person
MATCH (p:Person)-[:DECIDED]->(d:Decision)
WHERE d.id IN $ids
RETURN d.id AS decision, p.id AS person, p.name AS name, coalesce(p.active, false) AS active,
       size([(p)-[:MEMBER_OF]->(t:Team)-[:OWNS]->(:Node)<-[:CONSTRAINS]-(d) | t.id]) > 0 AS on_owning_team
ORDER BY decision, person
LIMIT 50
