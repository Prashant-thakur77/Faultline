// id: Q-BLAST-1
// purpose: blast radius: everything a failure at $id can reach (algo.BFS over PROPAGATES_TO)
// seen: id
MATCH (s:Node {id:$id})
CALL {algo:bfs}(s, 8, 'PROPAGATES_TO') YIELD nodes
UNWIND nodes AS n
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, n.tier AS tier, n.revenue_path AS revenue
ORDER BY id
LIMIT 100
