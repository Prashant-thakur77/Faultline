// id: Q-GATE-2
// purpose: gate G3 time order: is the cause inside the window, and is there an earlier upstream change on its path?
// returns: single-row
// seen: earlier_upstream_changes
MATCH (c:Deploy {id:$cause})-[:CHANGED]->(cs)
OPTIONAL MATCH (cs)-[:DEPENDS_ON*1..8]->(up)<-[:CHANGED]-(earlier:Deploy)
WHERE earlier.at < c.at AND earlier.at >= $onset - $window_ms // lint: optional-where-ok
RETURN c.at <= $onset AND $onset <= c.at + $window_ms AS in_window, c.at AS cause_at, $onset AS onset_at,
       collect(DISTINCT earlier.id) AS earlier_upstream_changes
LIMIT 1
