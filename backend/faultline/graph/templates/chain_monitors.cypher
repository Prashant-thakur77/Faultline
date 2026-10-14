// id: Q-CHAIN-MON
// purpose: why alerts missed it: for each hop of the proven causal chain, the alerts that fired on it (and when) and whether it has telemetry at all
// seen: id
UNWIND range(0, size($chain) - 1) AS i
MATCH (n:Node {id: $chain[i]})
RETURN i AS hop, n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label,
       [(a:Alert)-[:FIRED_ON]->(n) WHERE a.fired_at >= $since AND a.fired_at <= $until | {id: a.id, at: a.fired_at, metric: a.metric}] AS alerts,
       size([(m:MetricWindow)-[:WINDOW_OF]->(n) | m]) > 0 AS has_telemetry
ORDER BY hop
LIMIT 20
