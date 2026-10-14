// id: Q-BASE-1
// purpose: healthy baseline series of a metric on a target (bands are computed in code from these values)
MATCH (w:MetricWindow {target_id:$target, metric:$metric, kind:'baseline'})
RETURN w.day AS day, w.value AS value
ORDER BY day
LIMIT 100
