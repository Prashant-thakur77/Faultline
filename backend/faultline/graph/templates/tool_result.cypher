// id: Q-EV-TOOL
// purpose: the latest recorded result of a tool in a run (what the agent saw: cut, what-if, who fixes it, …)
// returns: single-row
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(tc:ToolCall {tool:$tool})-[:PRODUCED_EVIDENCE]->(e:Evidence)
RETURN tc.id AS id, e.id AS evidence_id, e.summary AS summary, e.payload AS payload, e.template AS template, e.params AS params, tc.at AS at
ORDER BY at DESC
LIMIT 1
