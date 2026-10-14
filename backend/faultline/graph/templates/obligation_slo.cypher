// id: Q-OBL-SLO
// purpose: obligation clock: error-budget burn of every SLO on the failing component and its blast radius (algo.BFS over PROPAGATES_TO, 8 hops). From the (:MetricWindow)-[:WINDOW_OF]-> telemetry: the current error rate (mean over [$current_since, $now]), burn = current rate / budget, and the budget remaining = 1 - spent before the telemetry horizon - error-minutes in the SLO window / budget-minutes
// seen: slo, service
// (comprehension + reduce instead of OPTIONAL MATCH + aggregation: an SLO with no telemetry still returns a row, burn null)
// (BFS inside an aggregating CALL subquery: algo.BFS yields NO row when nothing is reachable, which would drop the SLO of the failing component itself)
MATCH (s:Node {id:$id})
CALL { WITH s CALL {algo:bfs}(s, 8, 'PROPAGATES_TO') YIELD nodes UNWIND nodes AS x RETURN collect(x) AS reached }
UNWIND reached + [s] AS n
MATCH (o:SLO)-[:FOR]->(n)
WITH o, n, [(w:MetricWindow)-[:WINDOW_OF]->(n) WHERE w.kind = 'live' AND w.metric = o.metric AND w.at <= $now AND w.at > $now - o.window_days * 86400000 | w] AS ws
WITH o, n, ws, [w IN ws WHERE w.at >= $current_since | w.value] AS cur
WITH o, n, size(ws) AS windows, size(cur) AS current_windows, reduce(t = 0.0, w IN ws | t + w.value) AS error_minutes,
     CASE WHEN size(cur) = 0 THEN null ELSE reduce(t = 0.0, v IN cur | t + v) / size(cur) END AS error_rate
RETURN o.id AS slo, n.id AS service, [x IN labels(n) WHERE x <> 'Node'][0] AS label, n.tier AS tier,
       o.objective AS objective, o.budget AS budget, o.window_days AS window_days, o.spent_prior AS spent_prior,
       windows, current_windows, error_rate,
       CASE WHEN error_rate IS NULL THEN null ELSE error_rate / o.budget END AS burn,
       1.0 - o.spent_prior - error_minutes / (o.budget * o.window_days * 1440.0) AS budget_remaining
ORDER BY coalesce(burn, -1.0) DESC, slo
LIMIT 100
