// id: Q-LEVER-PATH
// purpose: does a containment lever matter for THIS incident: is the cut edge ($u -> $v) on a PROPAGATES_TO failure path from the origin to one of the incident symptoms, within the gate path bound of 8 hops? A min-cut edge protects the entry set; a flag on an edge no path to the symptoms crosses changes nothing the incident is about (without this check, S2 was offered a service flag for a KPI data incident)
// returns: single-row
// seen: symptoms_reached
MATCH (o:Node {id: $origin}), (u:Node {id: $u}), (v:Node {id: $v})
CALL {
  WITH o, u
  MATCH p1 = (o)-[:PROPAGATES_TO*0..8]->(u)
  RETURN min(length(p1)) AS before
}
CALL {
  WITH u, v
  MATCH (u)-[e:PROPAGATES_TO]->(v)
  RETURN count(e) AS edge
}
CALL {
  WITH v
  MATCH p2 = (v)-[:PROPAGATES_TO*0..8]->(s:Node)
  WHERE s.id IN $symptoms
  WITH s, min(length(p2)) AS after
  RETURN collect([s.id, after]) AS reach
}
WITH [x IN reach WHERE before IS NOT NULL AND edge > 0 AND before + 1 + x[1] <= 8 | x[0]] AS reached
RETURN reached AS symptoms_reached, size(reached) > 0 AS on_path
LIMIT 1
