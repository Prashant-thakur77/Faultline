// id: Q-STORM-ATTACH
// purpose: attach-or-open (runs on the scratch projection of Q-STORM-EDGES): for each alert, the OPEN incidents whose confirmed origin reaches the alert target over failure-carrying PROPAGATES_TO edges within 6 hops (0 = the origin itself alerts); only the nearest incidents are kept
// seen: alert, incident
MATCH (o:Node) WHERE size(coalesce(o.origin_of, [])) > 0
MATCH p = (o)-[:PROPAGATES_TO*0..6]->(t:Node)
WHERE size(coalesce(t.alerts, [])) > 0
WITH o, t, min(length(p)) AS hops
UNWIND o.origin_of AS incident
UNWIND t.alerts AS alert
WITH alert, incident, min(hops) AS hops
WITH alert, collect({incident: incident, hops: hops}) AS cands, min(hops) AS best
UNWIND cands AS c
WITH alert, c, best WHERE c.hops = best
RETURN alert, c.incident AS incident, c.hops AS hops
ORDER BY alert, incident
LIMIT 100
