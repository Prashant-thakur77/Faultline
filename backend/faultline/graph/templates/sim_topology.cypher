// id: Q-SIM-1
// purpose: service/datastore failure-flow edges with criticality and call share (input to the telemetry simulator: the world, not the agent)
MATCH (a:Node)-[r:PROPAGATES_TO]->(b:Node)
WHERE (a:Service OR a:Datastore) AND (b:Service OR b:Datastore)
MATCH (b)-[c:CALLS]->(a)
WITH a, b, r, c
MATCH ()-[ci:CALLS]->(b)
WITH a, b, r, c, sum(ci.rps) AS in_rps
RETURN a.id AS src, b.id AS dst, r.cap AS cap, c.rps AS rps, in_rps
ORDER BY src, dst
LIMIT 100
