// id: Q-GATE-OBS
// purpose: gate G5 observed impact: error-rate / row-share measurements this run recorded ABOUT the given nodes
// seen: about
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)-[:ABOUT]->(n:Node)
WHERE e.kind IN ['error_rate', 'row_share'] AND n.id IN $ids
RETURN e.id AS evidence, e.kind AS kind, n.id AS about, e.value AS value, e.baseline AS baseline, e.at AS at
ORDER BY at DESC, evidence
LIMIT 50
