// id: Q-CREW-LAST
// purpose: the last completed crew step of a run (the agent the next step is handed off from)
// returns: single-row
MATCH (run:Run {id: $run})-[:HAS_TASK]->(t:Task)
WHERE t.kind = 'crew' AND t.state IN ['done', 'failed']
RETURN t.id AS task, t.owner AS owner, t.stage AS stage, t.done_at AS done_at
ORDER BY t.done_at DESC, t.id DESC
LIMIT 1
