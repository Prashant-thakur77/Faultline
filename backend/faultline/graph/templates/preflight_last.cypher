// id: Q-PRE-LAST
// purpose: the latest recorded preflight of a PR (the evidence its preflight_change call produced), for deep links from the PR comment
// returns: single-row
// seen: run
MATCH (run:Run {mode:'preflight'})-[:HAS_TOOL_CALL]->(tc:ToolCall {tool:'preflight_change'})-[:PRODUCED_EVIDENCE]->(e:Evidence)
WHERE run.question STARTS WITH $pr
RETURN run.id AS run, e.id AS evidence_id, e.payload AS payload, e.params AS params, e.cypher AS cypher, tc.at AS at
ORDER BY at DESC
LIMIT 1
