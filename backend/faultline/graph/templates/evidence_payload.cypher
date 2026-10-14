// id: Q-EV-PAYLOAD
// purpose: specialist contract validation: the recorded payload of each cited evidence item this run produced; a contract's observations must appear in it
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)
WHERE e.id IN $ids
RETURN DISTINCT e.id AS id, e.tool AS tool, e.payload AS payload
ORDER BY id
LIMIT 100
