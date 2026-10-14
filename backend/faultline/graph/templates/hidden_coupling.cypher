// id: Q-COUPLE-1
// purpose: hidden coupling: a component whose changes caused incidents that repeatedly hit another component with NO PROPAGATES_TO path between them (within 8 hops): the graph is probably missing an edge
// seen: cause, hit, incidents
// strength = FalkorDB FLEX flex.sim.jaccard(incidents caused at `cause`, incidents where `hit` was impacted or the symptom; incidents
// `hit` itself caused do not count): 1.0 means every one of them co-failed. One inline-role comprehension per WITH (engine bugs #9, #13)
MATCH (i:Incident)-[c:AFFECTED]->(a:Node), (i)-[x:AFFECTED]->(b:Node)
WHERE c.role = 'cause' AND x.role IN ['impacted', 'symptom'] AND a.id <> b.id
  AND (size($from) = 0 OR a.id IN $from OR b.id IN $from)
WITH a, b, count(DISTINCT i) AS n, collect(DISTINCT i.id) AS incs
WHERE n >= $min_incidents AND NOT (a)-[:PROPAGATES_TO*1..8]->(b)
WITH a, b, n, incs, [(a)<-[:AFFECTED {role: 'cause'}]-(ca:Incident) | ca.id] AS caused
WITH a, b, n, incs, caused, [(b)<-[:AFFECTED {role: 'impacted'}]-(hi:Incident) | hi.id] AS hit_impacted
WITH a, b, n, incs, caused, hit_impacted, [(b)<-[:AFFECTED {role: 'symptom'}]-(hs:Incident) | hs.id] AS hit_symptom
RETURN a.id AS cause, b.id AS hit, n AS co_failures, incs[0..5] AS incidents,
       flex.sim.jaccard(caused, hit_impacted + hit_symptom) AS strength,
       size([(a)-[:DEPENDS_ON|CALLS|READS|WRITES]-(b) | 1]) > 0 AS adjacent
ORDER BY strength DESC, co_failures DESC, cause, hit
LIMIT 50
