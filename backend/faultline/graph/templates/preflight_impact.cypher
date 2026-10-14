// id: Q-PRE-1
// purpose: preflight: what a PR's changed components can reach if they fail (algo.BFS over PROPAGATES_TO), with tier and revenue flags
// seen: changed, impacted
// (revenue-path and tier-1 rows first, scale benchmark finding: on a 10k-service tenant a global hub reaches far more than
//  100 nodes and the alphabetical order kept none of the revenue path, so the revenue term read 0 and the verdict fell
//  from require_review to allow. Untruncated results are the same row set as before; only which rows survive the cap changes)
MATCH (pr:PR {id:$pr})-[:TOUCHES]->(:File)-[:PART_OF]->(s)
WITH DISTINCT s
CALL {algo:bfs}(s, 6, 'PROPAGATES_TO') YIELD nodes
UNWIND nodes AS n
RETURN s.id AS changed, n.id AS impacted, n.tier AS tier, coalesce(n.revenue_path, false) AS revenue
ORDER BY revenue DESC, coalesce(tier, 9), changed, impacted
LIMIT 100
