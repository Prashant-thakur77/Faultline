// Every change that landed in the alert window, with the component it changed. Params: $onset (epoch ms), $window_ms.
MATCH (d:Deploy)-[:CHANGED]->(x)
WHERE d.at >= $onset - $window_ms AND d.at <= $onset
RETURN d.id AS change, d.kind AS kind, x.id AS component, d.at AS at
ORDER BY at DESC, change
LIMIT 50
