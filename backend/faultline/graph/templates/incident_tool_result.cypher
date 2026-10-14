// id: Q-EV-INC-TOOL
// purpose: the latest recorded result of a tool in any run of an incident (the report re-reads what the run saw instead of recomputing it)
// returns: single-row
MATCH (:Incident {id:$inc})-[:HAS_RUN]->(:Run)-[:HAS_TOOL_CALL]->(tc:ToolCall {tool:$tool})-[:PRODUCED_EVIDENCE]->(e:Evidence)
RETURN tc.id AS id, e.id AS evidence_id, e.payload AS payload, e.params AS params, tc.at AS at
ORDER BY at DESC
LIMIT 1
