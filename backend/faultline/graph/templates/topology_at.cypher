// id: Q-TOPO-AT
// purpose: what a component could break AT a past time vs now: its failure reach over PROPAGATES_TO (1..6 hops) using only the calls that existed then (valid_from <= $at), the reach now (algo.BFS), the components added since, and every call introduced after $at inside today's reach with the PR that introduced it
// returns: single-row
// seen: then_reach, added, now_reach
MATCH (s:Node {id: $id})
CALL {
  WITH s
  MATCH p = (s)-[:PROPAGATES_TO*1..6]->(n)
  WHERE all(r IN relationships(p) WHERE coalesce(r.valid_from, 0) <= $at)
  RETURN collect(DISTINCT n.id) AS then_reach
}
CALL {
  WITH s
  CALL {algo:bfs}(s, 6, 'PROPAGATES_TO') YIELD nodes
  RETURN [x IN nodes | x.id] AS now_reach
}
CALL {
  WITH s, now_reach
  MATCH (a:Node)-[r:PROPAGATES_TO]->(b:Node)
  WHERE r.valid_from > $at AND b.id IN now_reach AND (a.id = s.id OR a.id IN now_reach)
  WITH a, b, r
  ORDER BY r.valid_from, a.id, b.id
  RETURN collect({from: a.id, to: b.id, at: r.valid_from, pr: r.introduced_by}) AS calls_since
}
RETURN s.id AS id, then_reach, now_reach, [x IN now_reach WHERE NOT x IN then_reach] AS added, calls_since
LIMIT 1
