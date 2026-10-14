// id: Q-MEM-5
// purpose: what the recalled precedents teach about each fix kind: how often it was APPLIED vs NOT_APPLIED (procedural memory for the plan)
// seen: incidents
MATCH (cur:Incident {id:$inc})-[:RECALLED]->(p:Incident)-[:RESOLVED_BY|ATTEMPTED]->(a:Action)
RETURN a.kind AS kind, a.verdict AS verdict, count(DISTINCT p) AS n, collect(DISTINCT p.id) AS incidents
ORDER BY kind, verdict
LIMIT 20
