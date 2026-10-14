// id: Q-PROTECT-1
// purpose: what containment must protect: the entry services the failing component can actually reach (algo.BFS over PROPAGATES_TO), not the first entries tenant-wide (at scale the incident's own entry was missing: scale bench finding). Ranked tier-1 first, then revenue path, then id, so a cap keeps the most important entries; every row carries how many entries are reachable in all (total) and how many of them are tier 1 (tier1), so the caller can say that more exist and refuse a cap that would drop a tier-1 entry
// seen: id
MATCH (t:Node {id: $target})
CALL { WITH t CALL {algo:bfs}(t, 8, 'PROPAGATES_TO') YIELD nodes RETURN nodes }
UNWIND nodes AS s
WITH DISTINCT s
WHERE s:Service AND s.entry = true AND s.id <> $target
WITH collect(s) AS entries, count(s) AS total, sum(CASE WHEN s.tier = 1 THEN 1 ELSE 0 END) AS tier1
UNWIND entries AS s
RETURN s.id AS id, 'entry' AS kind, s.tier AS tier, coalesce(s.revenue_path, false) AS revenue, total, tier1
ORDER BY coalesce(tier, 9), revenue DESC, id
LIMIT 20
