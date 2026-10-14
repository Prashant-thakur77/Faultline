// id: Q-TASK-1
// purpose: coordination (T2): task owners and handoffs for a set of tasks
// seen: task, owner
MATCH (t:Task) WHERE t.id IN $ids
RETURN t.id AS task, t.state AS state, t.owner AS owner, t.n AS n,
       [(t)-[:CLAIMED_BY]->(a:Agent) | a.id] AS claimed_by
ORDER BY task
LIMIT 100
