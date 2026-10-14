// id: Q-WHATIF-1
// purpose: what-if (on a GRAPH.COPY branch with cut edges removed): what can the failing component still reach? (algo.BFS over PROPAGATES_TO)
// seen: reached
MATCH (f:Node {id:$failing})
CALL {algo:bfs}(f, 8, 'PROPAGATES_TO') YIELD nodes
RETURN [n IN nodes | n.id] AS reached
ORDER BY size(reached)
LIMIT 1
