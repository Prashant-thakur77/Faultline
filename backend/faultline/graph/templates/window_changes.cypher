// id: Q-SUS-2
// purpose: every change in the window anywhere (this is where look-alike distractors enter)
// seen: deploy, target
MATCH (d:Deploy)-[:CHANGED]->(x)
WHERE d.at >= $onset - $window_ms AND d.at <= $onset
RETURN d.id AS deploy, d.kind AS kind, x.id AS target, d.at AS at
ORDER BY at DESC, deploy
LIMIT 50
