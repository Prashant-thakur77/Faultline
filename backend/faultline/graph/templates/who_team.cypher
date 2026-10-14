// id: Q-ORG-TEAM
// purpose: who-fixes input: the owner team, its active members and the component's files
// returns: single-row
// seen: team, members, files
MATCH (c:Node {id:$target})
OPTIONAL MATCH (t:Team)-[:OWNS]->(c)
OPTIONAL MATCH (m:Person)-[:MEMBER_OF]->(t)
WHERE m.active // lint: optional-where-ok
OPTIONAL MATCH (f:File)-[:PART_OF]->(c)
RETURN c.id AS target, t.id AS team, collect(DISTINCT m.id) AS members, collect(DISTINCT f.id) AS files
LIMIT 1
