// id: Q-PRE-FLOW
// purpose: preflight v2 exposure (M15 #6, a pre-registered backtest variant): the most failure a PR's changed components can push into the revenue path and tier-1 nodes, algo.maxFlow over PROPAGATES_TO.cap. Read on the graph as of the merge (the backtest runs it on a GRAPH.COPY branch per topology epoch with the calls introduced later removed). No source or no target means no row
// returns: single-row
// seen: flow
MATCH (pr:PR {id: $pr})-[:TOUCHES]->(:File)-[:PART_OF]->(s)
WITH collect(DISTINCT s) AS srcs
MATCH (t:Node)
WHERE (coalesce(t.revenue_path, false) OR t.tier = 1) AND NOT t IN srcs
WITH srcs, collect(t) AS tgts
WHERE size(srcs) > 0 AND size(tgts) > 0
CALL {algo:maxflow}({sourceNodes: srcs, targetNodes: tgts, relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow
RETURN maxFlow AS flow, size(srcs) AS sources, size(tgts) AS targets
LIMIT 1
