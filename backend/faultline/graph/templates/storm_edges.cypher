// id: Q-STORM-EDGES
// purpose: alert-storm projection (INTAKE): the PROPAGATES_TO edges among the alerting targets and their upstream (6 hops) that can carry an alert-worthy rise, i.e. criticality x the source measured excess (peak in the alert window minus its pre-window mean) reaches $carry_min; a source with no error-rate windows counts as able to carry
// seen: src, dst
// (hop bound 6, shared with Q-PRIMARY-1 and Q-STORM-ATTACH; tests/graph/test_template_lint.py keeps them equal)
MATCH (t:Node) WHERE t.id IN $targets
MATCH (u:Node)-[:PROPAGATES_TO*0..6]->(t)
WITH collect(DISTINCT u.id) AS region
MATCH (u:Node)-[r:PROPAGATES_TO]->(v:Node)
WHERE u.id IN region AND v.id IN region
CALL {
  WITH u
  MATCH (w:MetricWindow {target_id: u.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS base, max(CASE WHEN w.at >= $since THEN w.value END) AS peak
}
WITH u, v, coalesce(r.cap, 1.0) AS cap, coalesce(peak - base, 1.0) AS excess
WHERE cap * excess >= $carry_min
RETURN u.id AS src, v.id AS dst, cap, excess, cap * excess AS carry
ORDER BY src, dst
LIMIT 100
