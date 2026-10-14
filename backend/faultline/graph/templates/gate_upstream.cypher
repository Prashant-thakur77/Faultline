// id: Q-GATE-UPSTREAM
// purpose: sweep, G4 upstream ELIMINATION under a strict lower bound (deep bench + adversarial review): for each suspect's changed component s, a component u upstream whose own measured fault fully accounts for s's anomaly: u's excess >= $min_excess, u's anomaly started no later than s's, no failure path leads back from s to u, and s's excess <= u's excess x the BEST SINGLE path's product of cap x share (share = the call share recorded on each PROPAGATES_TO edge at ingest, the propagation the services actually see; a hop without a share, e.g. data plane or a learned link, makes the path unusable). No slack: any surplus at s may be its own fault, so s stays a candidate. Excess = peak since $since minus the pre-onset baseline mean; onset = the first window after the baseline whose rise is >= $min_excess
// seen: u, s
// engine bug #19 (docs/upstream/19): a MATCH after a CALL subquery ignores a variable bound before the CALL, so both
// MATCHes come first and every CALL only reads
MATCH (s:Node) WHERE s.id IN $ids
MATCH (u:Node)-[:PROPAGATES_TO*1..8]->(s)
WITH DISTINCT u, s
CALL {
  WITH u, s
  OPTIONAL MATCH back = (s)-[:PROPAGATES_TO*1..8]->(u)
  WITH back LIMIT 1
  RETURN count(back) AS backpaths
}
CALL {
  WITH s
  MATCH (w:MetricWindow {target_id: s.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  WITH collect(w) AS ws
  WITH ws, [x IN ws WHERE x.at <= $base_until | x.value] AS bv
  WITH ws, CASE WHEN size(bv) = 0 THEN null ELSE reduce(a = 0.0, v IN bv | a + v) / size(bv) END AS base
  RETURN base AS sbase,
         reduce(m = null, x IN ws | CASE WHEN x.at >= $since AND (m IS NULL OR x.value > m) THEN x.value ELSE m END) AS speak,
         reduce(o = null, x IN ws | CASE WHEN base IS NOT NULL AND x.at > $base_until AND x.value - base >= $min_excess
                                          AND (o IS NULL OR x.at < o) THEN x.at ELSE o END) AS sonset
}
CALL {
  WITH u
  MATCH (w:MetricWindow {target_id: u.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  WITH collect(w) AS ws
  WITH ws, [x IN ws WHERE x.at <= $base_until | x.value] AS bv
  WITH ws, CASE WHEN size(bv) = 0 THEN null ELSE reduce(a = 0.0, v IN bv | a + v) / size(bv) END AS base
  RETURN base AS ubase,
         reduce(m = null, x IN ws | CASE WHEN x.at >= $since AND (m IS NULL OR x.value > m) THEN x.value ELSE m END) AS upeak,
         reduce(o = null, x IN ws | CASE WHEN base IS NOT NULL AND x.at > $base_until AND x.value - base >= $min_excess
                                          AND (o IS NULL OR x.at < o) THEN x.at ELSE o END) AS uonset
}
CALL {
  WITH u, s
  MATCH p = (u)-[:PROPAGATES_TO*1..8]->(s)
  WITH p LIMIT 1001
  WITH p, all(r IN relationships(p) WHERE r.cap IS NOT NULL AND r.share IS NOT NULL) AS usable
  RETURN count(p) AS paths, min(length(p)) AS hops,
         max(CASE WHEN usable THEN reduce(acc = 1.0, r IN relationships(p) | acc * r.cap * r.share) END) AS best
}
WITH u, s, hops, backpaths, sonset, uonset,
     CASE WHEN speak IS NULL OR sbase IS NULL THEN null WHEN speak - sbase > 0.0 THEN speak - sbase ELSE 0.0 END AS sex,
     CASE WHEN upeak IS NULL OR ubase IS NULL THEN null WHEN upeak - ubase > 0.0 THEN upeak - ubase ELSE 0.0 END AS uex,
     CASE WHEN paths > 1000 THEN null ELSE best END AS transfer
WITH u, s, hops, backpaths, sonset, uonset, sex, uex, transfer,
     CASE WHEN transfer IS NULL OR uex IS NULL THEN null WHEN transfer * uex > 1.0 THEN 1.0 ELSE transfer * uex END AS carried
WHERE sex IS NOT NULL AND sex > 0.0 AND uex IS NOT NULL AND uex >= $min_excess AND backpaths = 0
  AND carried IS NOT NULL AND sex <= carried
  AND uonset IS NOT NULL AND sonset IS NOT NULL AND uonset <= sonset
RETURN s.id AS s, u.id AS u, hops, transfer, uex AS u_excess, sex AS s_excess, carried, uonset AS u_onset, sonset AS s_onset
ORDER BY s, hops, u
LIMIT 100
