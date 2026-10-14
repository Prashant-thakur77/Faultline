// id: Q-GATE-UPSTREAM-UB
// purpose: confirm phase, G4 upstream DOWNGRADE-ONLY check (deep bench + adversarial review): for the confirmed change's components s, any component u upstream (a failure path of 1..8 hops, no path back) whose measured excess could carry s's under the GENEROUS upper bound: s's excess <= min(1, u's excess x transfer) x $slack, transfer = Q-FUTURE-1's model (sum over the PROPAGATES_TO paths of the product of the caps), u's excess >= $min_excess. A row means the change may not be the origin, so the claim is downgraded to not confident; it never eliminates anything (an upper bound may only make the gate more careful). Excess = peak since $since minus the pre-onset baseline mean, from MetricWindows
// seen: u, s
// engine bug #19 (docs/upstream/19): a MATCH after a CALL subquery ignores a variable bound before the CALL, so both
// MATCHes come first and every CALL only reads
MATCH (s:Node) WHERE s.id IN $ids
MATCH (u:Node)-[:PROPAGATES_TO*1..8]->(s)
WITH DISTINCT u, s
CALL {
  WITH s
  MATCH (w:MetricWindow {target_id: s.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS sbase, max(CASE WHEN w.at >= $since THEN w.value END) AS speak
}
CALL {
  WITH u
  MATCH (w:MetricWindow {target_id: u.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS ubase, max(CASE WHEN w.at >= $since THEN w.value END) AS upeak
}
CALL {
  WITH u, s
  MATCH p = (u)-[:PROPAGATES_TO*1..8]->(s)
  WITH p LIMIT 1001
  RETURN count(p) AS paths, min(length(p)) AS hops,
         sum(CASE WHEN any(r IN relationships(p) WHERE r.cap IS NULL) THEN 1 ELSE 0 END) AS uncapped,
         sum(reduce(acc = 1.0, r IN relationships(p) | acc * coalesce(r.cap, 1.0))) AS walk
}
CALL {
  WITH u, s
  OPTIONAL MATCH back = (s)-[:PROPAGATES_TO*1..8]->(u)
  WITH back LIMIT 1
  RETURN count(back) AS backpaths
}
WITH u, s, hops, backpaths,
     CASE WHEN speak IS NULL OR sbase IS NULL THEN null WHEN speak - sbase > 0.0 THEN speak - sbase ELSE 0.0 END AS sex,
     CASE WHEN upeak IS NULL OR ubase IS NULL THEN null WHEN upeak - ubase > 0.0 THEN upeak - ubase ELSE 0.0 END AS uex,
     CASE WHEN paths > 1000 OR uncapped > 0 THEN null ELSE walk END AS transfer
WITH u, s, hops, backpaths, sex, uex, transfer,
     CASE WHEN transfer IS NULL OR uex IS NULL THEN null WHEN transfer * uex > 1.0 THEN 1.0 ELSE transfer * uex END AS carried
WHERE sex IS NOT NULL AND sex > 0.0 AND uex IS NOT NULL AND uex >= $min_excess AND backpaths = 0
  AND carried IS NOT NULL AND sex <= carried * $slack
RETURN s.id AS s, u.id AS u, hops, transfer, uex AS u_excess, sex AS s_excess, carried
ORDER BY s, hops, u
LIMIT 100
