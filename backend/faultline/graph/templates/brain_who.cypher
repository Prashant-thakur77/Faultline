// id: Q-BRAIN-WHO
// purpose: company brain: who has worked on a component (commits, past incidents they resolved, team), most work first
// seen: person, teams
MATCH (c:Node {id:$target})<-[k:COMMITTED]-(p:Person)
RETURN p.id AS person, p.name AS name, p.active AS active, k.n AS commits, k.last_at AS last_commit_at,
       size([(p)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(c) | i]) AS incidents_resolved,
       [(p)-[:MEMBER_OF]->(t:Team) | t.id] AS teams
ORDER BY commits DESC, person
LIMIT 10
