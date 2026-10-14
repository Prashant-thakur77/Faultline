// id: Q-CHANGE-2
// purpose: a change's details (kind, time, actor, title, what it touched, the facts it asserts)
// returns: single-row
// seen: id, target
MATCH (d:Deploy {id:$id})
OPTIONAL MATCH (d)-[:CHANGED]->(t:Node)
RETURN d.id AS id, d.kind AS kind, d.at AS at, d.title AS title, d.actor_id AS actor, d.sha AS sha, t.id AS target,
       [(d)-[:ASSERTS]->(f:ChangeFact) | [f.key, f.value]] AS facts
LIMIT 1
