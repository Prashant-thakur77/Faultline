// id: Q-OBL-CUST
// purpose: obligation clock: customers reached through the failure. (:Customer)-[:CONSUMES]->(the failing component or anything in its blast radius, algo.BFS over PROPAGATES_TO, 8 hops), ONE row per distinct customer (a customer reached by several paths counts once) with every node that reached them, the nearest failure path (shortestPath) and, on every row, the revenue at risk = sum of mrr over the distinct customers
// seen: customer, through, path
// (BFS inside an aggregating CALL subquery: algo.BFS yields NO row when nothing is reachable, which would drop customers of the failing component itself)
MATCH (s:Node {id:$id})
CALL { WITH s CALL {algo:bfs}(s, 8, 'PROPAGATES_TO') YIELD nodes UNWIND nodes AS x RETURN collect(x) AS reached }
WITH s, reached + [s] AS reach
UNWIND reach AS n
MATCH (c:Customer)-[v:CONSUMES]->(n)
WITH c, n, v.via AS via, shortestPath((s)-[:PROPAGATES_TO*0..8]->(n)) AS p
WITH c, n, via, [x IN nodes(p) | x.id] AS path
ORDER BY size(path), n.id
WITH c, collect(n.id) AS through, collect(via) AS vias, collect(path) AS paths
WITH collect({c: c, through: through, vias: vias, path: paths[0]}) AS reached, sum(c.mrr) AS revenue_at_risk, count(c) AS customers_reached
UNWIND reached AS r
RETURN r.c.id AS customer, r.c.name AS name, r.c.tier AS tier, r.c.mrr AS mrr, r.through AS through, r.vias AS via,
       size(r.through) AS paths, r.path AS path, size(r.path) - 1 AS hops, revenue_at_risk, customers_reached
ORDER BY mrr DESC, customer
LIMIT 100
