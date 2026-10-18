// id: Q-REPAIR-TARGETS
// purpose: where a measured data repair can be applied: the row-share measurements this run recorded anomalous (Evidence.anomalous, decided in code when recorded), each ABOUT exactly one table and one column, joined to the Transform whose SQL WRITES that table (a source table nobody builds is left out), ordered nearest the confirmed cause first along the proof path ($chain, the gate's G2 chain)
// seen: evidence, table, column, transform
MATCH (run:Run {id: $run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence {kind: 'row_share'})-[:ABOUT]->(n:Node)
WHERE e.anomalous = true
WITH e, [x IN collect(DISTINCT n.id) WHERE size(split(x, '.')) = 2] AS tables,
     [x IN collect(DISTINCT n.id) WHERE size(split(x, '.')) = 3] AS columns
WHERE size(tables) = 1 AND size(columns) = 1
WITH e, head(tables) AS table, head(columns) AS column
MATCH (t:Transform)-[:WRITES]->(x:Table {id: table})
WITH e, table, column, t, [i IN range(0, size($chain) - 1) WHERE $chain[i] = table | i] AS at
RETURN e.id AS evidence, table, column, e.params AS params, e.value AS share, t.id AS transform,
       [(t)-[:READS]->(r:Table) | r.id] AS reads, CASE WHEN size(at) = 0 THEN size($chain) ELSE at[0] END AS chain_index
ORDER BY chain_index, share DESC, evidence
LIMIT 20
