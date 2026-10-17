// id: Q-MW-1
// purpose: a component's error-rate windows in a time range (telemetry the agent reasons over, read from the graph)
MATCH (w:MetricWindow {target_id:$target, metric:$metric, kind:'live'})
WHERE w.at >= $since AND w.at <= $until
RETURN w.at AS at, w.minute AS minute, w.value AS value, w.source AS source
ORDER BY at
LIMIT 100
