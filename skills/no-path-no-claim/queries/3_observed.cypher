// The share of requests failing at the symptom beyond its own baseline: (peak since onset - pre-onset mean) / (1 - mean).
// Params: $symptom, $onset, $base_since (onset - 30 min), $base_until (onset - 5 min), $until (onset + 10 min).
MATCH (w:MetricWindow {target_id: $symptom, metric: 'error_rate', kind: 'live'})
WHERE w.at >= $base_since AND w.at <= $until
WITH avg(CASE WHEN w.at <= $base_until THEN w.value END) AS base, max(CASE WHEN w.at >= $onset THEN w.value END) AS peak
RETURN base, peak, CASE WHEN base IS NULL OR peak IS NULL OR base >= 1.0 THEN null
                        WHEN peak <= base THEN 0.0 ELSE (peak - base) / (1.0 - base) END AS observed_share
LIMIT 1
