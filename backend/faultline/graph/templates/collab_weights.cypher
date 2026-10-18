// id: Q-ORG-COLLAB-W
// purpose: escalation weights, computed in Cypher: one row per pair of the given people with any COLLABORATES or REPORTS_TO edge between them (either direction), weight = the strongest tie (a COLLABORATES edge's w, default 1.0; a reporting line 0.5), for algo.MSF (maximize) on a scratch graph
// seen: a, b
MATCH (a:Person)-[r:COLLABORATES|REPORTS_TO]-(b:Person)
WHERE a.id IN $ids AND b.id IN $ids AND a.id < b.id
RETURN a.id AS a, b.id AS b, max(CASE WHEN type(r) = 'COLLABORATES' THEN coalesce(r.w, 1.0) ELSE 0.5 END) AS w
ORDER BY a, b
LIMIT 100
