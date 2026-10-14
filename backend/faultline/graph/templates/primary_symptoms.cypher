// id: Q-PRIMARY-1
// purpose: independent alerts within ONE incident (its symptoms, which INTAKE grouped with algo.WCC over the same edges, Q-STORM-WCC): for each alerting target, the OTHER alerting targets that can carry an alert-worthy rise into it, over PROPAGATES_TO paths whose every edge has criticality x the source measured excess >= $carry_min (the Q-STORM-EDGES rule; a source with no error-rate windows counts as able to carry); a target with none is a primary; each primary is returned with its consequences (the targets it can carry a rise into), grouped here (M14 #6); a target no primary covers (fed only by a carrying cycle) is its own primary, so no symptom silently leaves G2/G5
// seen: primary, consequences
// (hop bound 6, the same as Q-STORM-EDGES and Q-STORM-ATTACH: the gate never calls a target a consequence over a path
//  INTAKE could not have grouped. The region is UPSTREAM of the targets; algo.BFS on 6.0.2 is positional (node, depth,
//  relType) and follows outgoing edges only, so the bounded var-length pattern stays)
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
WITH collect(CASE WHEN coalesce(r.cap, 1.0) * coalesce(peak - base, 1.0) >= $carry_min THEN id(r) END) AS carrying
MATCH (t:Node) WHERE t.id IN $targets
CALL {
  WITH t, carrying
  MATCH p = (o:Node)-[:PROPAGATES_TO*1..6]->(t)
  WHERE o.id IN $targets AND o.id <> t.id AND all(x IN relationships(p) WHERE id(x) IN carrying)
  RETURN collect(DISTINCT o.id) AS upstream_alerting
}
WITH t.id AS id, upstream_alerting
ORDER BY id
WITH collect({id: id, up: upstream_alerting}) AS rows
WITH rows, [x IN rows WHERE size(x.up) = 0 | x.id] AS prim
WITH rows, prim, [x IN rows WHERE any(q IN prim WHERE q IN x.up) | x.id] AS covered
UNWIND rows AS r
WITH r, rows, prim, covered
WHERE r.id IN prim OR NOT (r.id IN covered)
RETURN r.id AS primary, CASE WHEN r.id IN prim THEN [x IN rows WHERE r.id IN x.up | x.id] ELSE [] END AS consequences
ORDER BY primary
LIMIT 50
