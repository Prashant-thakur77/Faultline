// id: Q-VERIFY-ALLOW
// purpose: verification allowance (VERIFY channel 2, concurrent faults): an upper bound on the share of each symptom of this incident that OTHER open incidents still own, under the telemetry model (sim/telemetry.py: a node's excess rises by at most sum over its in-edges of cap x the source's excess, so a source's share at t is at most its excess x the sum over its paths to t of the product of caps). Qualifying origins: the confirmed origin of every other open incident (stage not terminal, not resolved) whose cause is a different change on a different component than this incident's confirmed causes, and that this incident's own origins do not reach at ANY depth (algo.BFS with max level -1 = unbounded, verified on the pinned engine; review round 4 m1: an 8-hop bound forgave our own leak beyond 8 hops): such an origin's excess carries our own leak. Per (symptom, origin): transfer = sum over PROPAGATES_TO paths of 1..8 hops (gate.max_len) that cross no cut edge ($cuts, "src|dst") and pass through no other qualifying origin (that origin's own measured excess already holds what flows through it, so the joint bound never counts shared capacity twice) of the product of the edges' cap; allowance = min(1, transfer x the origin's measured excess in the verification window: peak minus its mean over the pre-onset baseline, floored at 0). Unknown (null: allows nothing) when the excess is unmeasured, an edge has no cap, or more than 1000 paths. Several incidents blaming one origin are one row. No confirmed cause on this incident, or no qualifying origin, means no row (allowance 0)
// seen: incident, cause, origin, symptom
// (filters on WITH-projected variables sit in WITH … WHERE: on 6.0.2 a WHERE on the MATCH after an aggregating WITH sees them as null, docs/upstream/16)
MATCH (me:Incident {id: $inc})-[:HYPOTHESIZES]->(:Hypothesis {status: 'confirmed'})-[:BLAMES]->(mc:Node)-[:CHANGED|GATES]->(mo:Node)
CALL {
  WITH mo
  CALL {algo:bfs}(mo, -1, 'PROPAGATES_TO') YIELD nodes
  RETURN [n IN nodes | n.id] AS reach
}
WITH collect(DISTINCT mc.id) AS my_causes, collect(DISTINCT mo.id) AS my_origins, collect(reach) AS reaches
WITH my_causes, my_origins, reduce(acc = [], r IN reaches | acc + r) AS my_reach
WHERE size(my_causes) > 0
MATCH (i:Incident)-[:HYPOTHESIZES]->(:Hypothesis {status: 'confirmed'})-[:BLAMES]->(c:Node)-[:CHANGED|GATES]->(o:Node)
WHERE i.id <> $inc AND NOT i.stage IN $terminal AND i.resolved_at IS NULL
WITH DISTINCT i, c, o, my_causes, my_origins, my_reach
WHERE NOT c.id IN my_causes AND NOT o.id IN my_origins AND NOT o.id IN my_reach
WITH o.id AS oid, i.id AS iid, c.id AS cid
ORDER BY oid, iid, cid
WITH oid, collect(DISTINCT iid) AS incidents, collect(DISTINCT cid) AS causes
WITH collect({oid: oid, incidents: incidents, causes: causes}) AS others
WITH others, [x IN others | x.oid] AS other_ids
UNWIND others AS x
MATCH (o:Node {id: x.oid})
WITH x, o, other_ids
MATCH (t:Node) WHERE t.id IN $symptoms
WITH x, o, t, other_ids
WHERE t.id <> o.id
CALL {
  WITH o, t, other_ids
  MATCH p = (o)-[:PROPAGATES_TO*1..8]->(t)
  WITH p, o, t, other_ids
  WHERE none(r IN relationships(p) WHERE startNode(r).id + '|' + endNode(r).id IN $cuts)
    AND none(n IN nodes(p) WHERE n.id <> o.id AND n.id <> t.id AND n.id IN other_ids)
  WITH p LIMIT 1001
  RETURN count(p) AS paths, min(length(p)) AS hops,
         sum(CASE WHEN any(r IN relationships(p) WHERE r.cap IS NULL) THEN 1 ELSE 0 END) AS uncapped,
         sum(reduce(w = 1.0, r IN relationships(p) | w * coalesce(r.cap, 1.0))) AS walk
}
WITH x, o, t, paths, hops, uncapped, walk
WHERE paths > 0
CALL {
  WITH o
  MATCH (w:MetricWindow {target_id: o.id, metric: 'error_rate', kind: 'live'})
  WHERE w.at >= $base_since AND w.at <= $until
  RETURN avg(CASE WHEN w.at <= $base_until THEN w.value END) AS base, max(CASE WHEN w.at >= $since THEN w.value END) AS peak
}
WITH x, o, t, paths, hops, CASE WHEN paths > 1000 OR uncapped > 0 THEN null ELSE walk END AS transfer,
     CASE WHEN peak IS NULL OR base IS NULL THEN null WHEN peak - base > 0.0 THEN peak - base ELSE 0.0 END AS excess
RETURN t.id AS symptom, x.incidents[0] AS incident, x.incidents AS incidents, x.causes[0] AS cause, x.causes AS causes,
       o.id AS origin, hops, paths, transfer, excess,
       CASE WHEN excess IS NULL OR transfer IS NULL THEN null
            WHEN transfer * excess > 1.0 THEN 1.0 ELSE transfer * excess END AS allowance
ORDER BY symptom, origin
LIMIT 100
