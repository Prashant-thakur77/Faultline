// id: Q-RESIDUE-1
// purpose: residue check (advisory, never gating): every component this incident's runs MEASURED anomalous (the same Evidence.anomalous the gate reads), and whether it is downstream of the confirmed cause over the G2 relation set (CHANGED|GATES|PROPAGATES_TO, ≤ 8 hops). Unexplained ones mean another fault may be active
// seen: id
MATCH (c:Node {id:$cause})
MATCH (i:Incident {id:$inc})-[:HAS_RUN]->(:Run)-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence)-[:ABOUT]->(n:Node)
WHERE e.anomalous = true AND e.kind IN ['metric', 'profile', 'baseline_comparison', 'row_share', 'error_rate'] AND NOT n:Column
WITH c, n, collect(DISTINCT e.id) AS evidence, collect(DISTINCT e.kind) AS kinds
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, evidence, kinds,
       size([(c)-[:CHANGED|GATES|PROPAGATES_TO*1..8]->(n) | 1]) > 0 AS explained
ORDER BY explained DESC, id
LIMIT 100
