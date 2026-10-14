// id: Q-PRE-1-ASOF
// purpose: preflight impact AS OF a time (backtest, M14 #7): what the changed components could reach over PROPAGATES_TO (1..6 hops) using only the edges that existed then (valid_from <= $as_of; an edge without valid_from always existed). algo.BFS cannot filter edges by property, so this is a bounded path pattern; on both seeded tenants it returns exactly Q-PRE-1 reach when $as_of is after the whole history (checked on all 1273 PRs). Same columns and order as Q-PRE-1
// seen: changed, impacted
MATCH (pr:PR {id:$pr})-[:TOUCHES]->(:File)-[:PART_OF]->(s)
WITH DISTINCT s
MATCH p = (s)-[:PROPAGATES_TO*1..6]->(n)
WHERE all(r IN relationships(p) WHERE coalesce(r.valid_from, 0) <= $as_of)
WITH DISTINCT s, n
RETURN s.id AS changed, n.id AS impacted, n.tier AS tier, coalesce(n.revenue_path, false) AS revenue
ORDER BY revenue DESC, coalesce(tier, 9), changed, impacted
LIMIT 100
