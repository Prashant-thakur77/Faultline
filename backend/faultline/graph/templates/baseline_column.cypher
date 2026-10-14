// id: Q-BASE-2
// purpose: healthy observed range of a column (anomalous-row share input)
// returns: single-row
MATCH (b:Baseline)-[:BASELINE_OF]->(c:Column {id:$column})
RETURN b.id AS id, b.min AS min, b.max AS max, b.mean_lo AS mean_lo, b.mean_hi AS mean_hi, b.days AS days
LIMIT 1
