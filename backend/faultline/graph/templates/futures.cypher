// id: Q-FUTURE-1
// purpose: futures (CONTAIN): the predicted residual of the confirmed origin's fault at each target once a containment option is in place, read on that option's own GRAPH.COPY branch (its cut edges already removed; the live run graph for an option that cuts nothing). Model (the gate's and Q-VERIFY-ALLOW's, sim/telemetry.py): a node's excess rises by at most the sum over its in-edges of cap x the source's excess, so the origin's share at t is at most its excess x transfer, the sum over its PROPAGATES_TO paths of 1..8 hops (gate.max_len) of the product of the caps (the origin itself: transfer 1). Excess = the origin's peak since $since minus its mean over the pre-onset baseline, floored at 0, from its MetricWindows: what the graph measured, never the scenario's injected effect. residual = min(1, transfer x excess); 0 when the option removes the origin's fault ($removes_origin: rollback, data repair). Unknown (null) when the excess is unmeasured, an edge has no cap, or more than 1000 paths. Each target also returns its baseline windows (base_vals) and its peak since $since, so the caller applies VERIFY's own band rule
// seen: target, origin
MATCH (o:Node {id: $origin})
CALL {
  WITH o
  MATCH (w:MetricWindow {target_id: o.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS obase, max(CASE WHEN w.at >= $since THEN w.value END) AS opeak
}
WITH o, CASE WHEN opeak IS NULL OR obase IS NULL THEN null WHEN opeak - obase > 0.0 THEN opeak - obase ELSE 0.0 END AS excess
MATCH (t:Node) WHERE t.id IN $targets
CALL {
  WITH o, t
  OPTIONAL MATCH p = (o)-[:PROPAGATES_TO*1..8]->(t)
  WITH p LIMIT 1001
  RETURN count(p) AS paths, min(length(p)) AS hops,
         sum(CASE WHEN p IS NOT NULL AND any(r IN relationships(p) WHERE r.cap IS NULL) THEN 1 ELSE 0 END) AS uncapped,
         sum(CASE WHEN p IS NULL THEN 0.0 ELSE reduce(acc = 1.0, r IN relationships(p) | acc * coalesce(r.cap, 1.0)) END) AS walk
}
CALL {
  WITH t
  MATCH (w:MetricWindow {target_id: t.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN collect(CASE WHEN w.at <= $base_until THEN w.value END) AS base_vals,
         max(CASE WHEN w.at >= $since THEN w.value END) AS peak
}
WITH o, t, excess, paths, hops, base_vals, peak,
     CASE WHEN t.id = o.id THEN 1.0 WHEN paths > 1000 OR uncapped > 0 THEN null ELSE walk END AS transfer
RETURN t.id AS target, o.id AS origin, t.id = o.id AS is_origin, CASE WHEN t.id = o.id THEN 0 ELSE hops END AS hops,
       paths, transfer, excess, base_vals, peak,
       CASE WHEN $removes_origin THEN 0.0
            WHEN excess IS NULL OR transfer IS NULL THEN null
            WHEN transfer * excess > 1.0 THEN 1.0 ELSE transfer * excess END AS residual
ORDER BY target
LIMIT 50
