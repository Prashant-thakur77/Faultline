// id: Q-CITE-1
// purpose: citation guard: which of the cited ids were actually SEEN by a tool call of this run (a read-only query decides)
// returns: single-row
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:SAW]->(n:Node)
WHERE n.id IN $ids
RETURN collect(DISTINCT n.id) AS seen
LIMIT 1
