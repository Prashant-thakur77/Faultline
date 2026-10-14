// id: Q-GATE-7
// purpose: gate G7 agreement: independent channels (sources) whose cited evidence is ABOUT nodes of the causal chain
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)-[:ABOUT]->(n:Node)
WHERE e.id IN $evidence AND n.id IN $chain
RETURN e.source AS source, collect(DISTINCT e.id) AS evidence, collect(DISTINCT n.id) AS about
ORDER BY source
LIMIT 20
