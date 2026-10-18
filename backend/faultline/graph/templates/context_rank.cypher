// id: Q-CTX-RANK
// purpose: context pack: the window's changes upstream of the alerting nodes (Q-SUS-1's rows, one set per alerting node), each kept once at its nearest alerting node, with the error-rate excess measured on its changed component (peak since $since minus the pre-onset baseline mean, MetricWindows, the gate's windows; null without error-rate windows) and ranked IN THE ENGINE: rank 'anomaly' (default, PREREGISTRATION addendum 5) puts changes on components that broke first (excess >= $floor, by excess descending), then measured-but-quiet, then unmeasured; within each, and for rank 'distance', by hops, then most recent, then id
// seen: deploy, target, symptom
UNWIND $sus AS x
WITH x ORDER BY x.deploy, x.hops, x.symptom
WITH x.deploy AS deploy, collect(x)[0] AS b
MATCH (n:Node) WHERE n.id = b.target
CALL {
  WITH n
  MATCH (w:MetricWindow {target_id: n.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS base, max(CASE WHEN w.at >= $since THEN w.value END) AS peak
}
WITH deploy, b, CASE WHEN peak IS NULL OR base IS NULL THEN null ELSE peak - base END AS excess
WITH deploy, b, excess,
     CASE WHEN $rank = 'distance' THEN 0 WHEN excess IS NULL THEN 2 WHEN excess >= $floor THEN 0 ELSE 1 END AS grp
WITH deploy, b, excess, grp, CASE WHEN $rank = 'anomaly' AND grp = 0 THEN -excess ELSE 0.0 END AS by_excess
RETURN deploy, b.kind AS kind, b.target AS target, b.at AS at, b.hops AS hops, b.symptom AS symptom, excess, grp, by_excess
ORDER BY grp, by_excess, hops, at DESC, deploy
LIMIT 100
