// id: Q-DEC-PEOPLE
// purpose: who decided (M17): for each decision constraining a component, the people who DECIDED it, whether each is still active, and whether each is still on a team that OWNS what the decision constrains; plus the decision in force if it was superseded. Answers "who decided X, and are they still here?"
// seen: decision, person
MATCH (d:Decision)-[:CONSTRAINS]->(n:Node {id: $target})
OPTIONAL MATCH (p:Person)-[:DECIDED]->(d)
WITH d, n, p
RETURN d.id AS decision, d.title AS title, d.status AS status, d.decided_at AS decided_at, d.url AS url,
       p.id AS person, p.name AS name, coalesce(p.active, false) AS active,
       size([(p)-[:MEMBER_OF]->(t:Team)-[:OWNS]->(n) | t.id]) > 0 AS on_owning_team,
       [(d)<-[:SUPERSEDES*1..10]-(h:Decision {status: 'active'}) | h.id] AS superseded_by
ORDER BY decided_at DESC, decision, person
LIMIT 50
