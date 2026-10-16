// id: Q-SIM-2
// purpose: one page of the simulator failure-flow view, keyset-paged by (src, dst) (input to the telemetry simulator: the world, not the agent)
// Same columns as Q-SIM-1. Why paged: globex has 305 failure edges, more than one read, and the product-wide LIMIT
// cap (100) stays as it is; sim/telemetry.sim_view reads page after page until a page is not truncated.
// in_rps comes from a pattern comprehension, so a batch client with no inbound calls keeps its edges (in_rps 0, call
// share 1, the grader oracle convention) instead of dropping out of the simulated world as in the Q-SIM-1 join.
MATCH (a:Node)-[r:PROPAGATES_TO]->(b:Node)
WHERE (a:Service OR a:Datastore) AND (b:Service OR b:Datastore)
  AND (a.id > $after_src OR (a.id = $after_src AND b.id > $after_dst))
MATCH (b)-[c:CALLS]->(a)
RETURN a.id AS src, b.id AS dst, r.cap AS cap, c.rps AS rps,
       reduce(s = 0, x IN [()-[ci:CALLS]->(b) | ci.rps] | s + x) AS in_rps
ORDER BY src, dst
LIMIT 100
