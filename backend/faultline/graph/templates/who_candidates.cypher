// id: Q-ORG-1
// purpose: who fixes it: owner team, recent authors of the target, past resolvers on it, current on-call
// returns: single-row
// seen: target, team, recent_authors, past_resolvers, oncall
MATCH (c:Node {id:$target})
OPTIONAL MATCH (t:Team)-[:OWNS]->(c)
OPTIONAL MATCH (c)<-[:PART_OF]-(:File)<-[:TOUCHES]-(cm:Commit)<-[:AUTHORED]-(a:Person)
WHERE cm.at >= $since AND a.active // lint: optional-where-ok
OPTIONAL MATCH (r:Person)-[:RESOLVED]->(:Incident)-[:AFFECTED]->(c)
WHERE r.active // lint: optional-where-ok
OPTIONAL MATCH (o:Person)-[oc:ON_CALL]->(t)
WHERE oc.from <= $now AND $now < oc.to AND o.active // lint: optional-where-ok
RETURN c.id AS target, t.id AS team, collect(DISTINCT a.id) AS recent_authors, collect(DISTINCT r.id) AS past_resolvers,
       collect(DISTINCT o.id) AS oncall
LIMIT 1
