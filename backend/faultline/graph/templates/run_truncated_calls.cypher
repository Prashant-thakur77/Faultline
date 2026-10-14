// id: Q-RUN-TRUNC
// purpose: the run's tool calls whose read hit its template LIMIT (RO wrapper n+1 detection), for the scale benchmark and audits
// seen: id
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(tc:ToolCall)
WHERE tc.truncated = true
RETURN tc.id AS id, tc.tool AS tool, tc.template AS template, tc.rows AS rows
ORDER BY id
LIMIT 100
