// id: Q-GATE-ORIGIN
// purpose: sweep (origin test): for the suspects' changed components, the error-rate measurements THIS run recorded about them, and whether any was anomalous
// seen: id
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)-[:ABOUT]->(n:Node)
WHERE n.id IN $ids AND e.kind = 'error_rate' AND e.anomalous IS NOT NULL
RETURN n.id AS id, max(CASE WHEN e.anomalous THEN 1 ELSE 0 END) AS anomalous, collect(e.id) AS evidence
ORDER BY id
LIMIT 100
