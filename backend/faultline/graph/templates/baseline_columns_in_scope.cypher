// id: Q-BASE-3
// purpose: which columns of the given tables have a healthy baseline (what can be measured for anomalous rows)
// seen: table, column
MATCH (b:Baseline)-[:BASELINE_OF]->(c:Column)-[:OF]->(t:Table)
WHERE t.id IN $tables
RETURN t.id AS table, c.id AS column, c.name AS name, b.min AS min, b.max AS max
ORDER BY table, column
LIMIT 50
