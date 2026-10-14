// id: Q-GATE-CORR
// purpose: gate G7 structural correlation: for every specialist report of this run (a done specialist Task; crew step records are never votes), the deploys it NAMES, and the chain nodes it reaches by naming the cause Deploy through its CHANGED edge (non-empty `via` = this report names the cause, and the cause CHANGED a node of the G2 chain)
MATCH (run:Run {id:$run})-[:HAS_TASK]->(t:Task)
WHERE t.state = 'done' AND t.kind = 'specialist' AND t.role IN $roles
RETURN t.role AS role, t.status AS status, t.id AS task,
       [(t)-[:NAMES]->(d:Deploy) | d.id] AS named,
       [(t)-[:NAMES]->(d:Deploy)-[:CHANGED]->(x:Node) WHERE d.id = $cause AND x.id IN $chain | x.id] AS via
ORDER BY role, task
LIMIT 20
