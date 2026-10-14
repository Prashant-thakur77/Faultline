// id: Q-GATE-4
// purpose: gate G4: cited quantitative evidence produced by this run that is ABOUT a node on the causal chain
// seen: about
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)-[:ABOUT]->(n:Node)
WHERE e.id IN $evidence AND n.id IN $chain AND e.kind IN ['metric', 'profile', 'baseline_comparison', 'row_share', 'error_rate']
RETURN e.id AS evidence, n.id AS about, e.kind AS kind, e.ratio AS ratio, e.band AS band, e.value AS value,
       e.baseline AS baseline, e.anomalous AS anomalous, e.summary AS summary
ORDER BY evidence, about
LIMIT 50
