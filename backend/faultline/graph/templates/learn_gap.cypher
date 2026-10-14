// id: Q-LEARN-GAP
// purpose: memory that changes the answer (M15 #4): after a verified fix of change $change, for each of the incident symptoms, is there a PROPAGATES_TO path from the changed component within the gate bound of 8 hops? Where there is none, the graph is missing a link the fix just demonstrated; the measured share (the symptom excess over the component excess in this incident windows, peak since $since minus the pre-onset mean, capped at 1) is what a learned edge would carry
// seen: origin, symptom
MATCH (c:Node {id: $change})-[:CHANGED]->(o:Node)
MATCH (s:Node) WHERE s.id IN $symptoms AND s.id <> o.id
CALL {
  WITH o, s
  MATCH p = (o)-[:PROPAGATES_TO*1..8]->(s)
  WITH p LIMIT 1
  RETURN count(p) AS paths
}
CALL {
  WITH o
  MATCH (w:MetricWindow {target_id: o.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS obase, max(CASE WHEN w.at >= $since THEN w.value END) AS opeak,
         collect(CASE WHEN w.at <= $base_until THEN w.value END) AS obase_vals
}
CALL {
  WITH s
  MATCH (w:MetricWindow {target_id: s.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS sbase, max(CASE WHEN w.at >= $since THEN w.value END) AS speak,
         collect(CASE WHEN w.at <= $base_until THEN w.value END) AS sbase_vals
}
WITH o, s, paths, opeak - obase AS oex, speak - sbase AS sex, obase, opeak, obase_vals, sbase, speak, sbase_vals
RETURN o.id AS origin, s.id AS symptom, paths > 0 AS has_path, oex AS origin_excess, sex AS symptom_excess,
       obase, opeak, obase_vals, sbase, speak, sbase_vals,
       CASE WHEN oex IS NULL OR sex IS NULL OR oex <= 0.0 OR sex <= 0.0 THEN null
            WHEN sex / oex > 1.0 THEN 1.0 ELSE sex / oex END AS share
ORDER BY symptom
LIMIT 20
