// id: Q-RUN-2
// purpose: the run's tool calls and the evidence each produced, with the params they ran with (trace panel, replay export, cost)
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(tc:ToolCall)
OPTIONAL MATCH (tc)-[:PRODUCED_EVIDENCE]->(e:Evidence)
RETURN tc.id AS id, tc.tool AS tool, tc.template AS template, tc.ms AS ms, tc.rows AS rows, tc.at AS at,
       e.id AS evidence_id, e.kind AS kind, e.summary AS summary, e.params AS params, e.digest AS digest
ORDER BY at, id
LIMIT 100
