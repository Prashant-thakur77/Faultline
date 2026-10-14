// id: Q-GATE-G1
// purpose: gate G1 grounding: which of $ids this run SAW in graph results, and which cited evidence ids it produced
// returns: single-row
// (pattern comprehensions, not OPTIONAL MATCH after an aggregating WITH: FalkorDB 6.0.2 returns nothing for the latter; docs/upstream/07)
MATCH (run:Run {id:$run})
RETURN [(run)-[:HAS_TOOL_CALL]->(:ToolCall)-[:SAW]->(n:Node) WHERE n.id IN $ids | n.id] AS seen,
       [(run)-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence) WHERE e.id IN $evidence | e.id] AS evidence
LIMIT 1
