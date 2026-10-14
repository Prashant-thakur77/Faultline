// id: Q-CHANGE-1
// purpose: what a change touched (Deploy -CHANGED-> target, FeatureFlag -GATES-> target); a non-change node is its own target
// seen: change, target
MATCH (c:Node {id:$id})
OPTIONAL MATCH (c)-[:CHANGED|GATES]->(t:Node)
RETURN c.id AS change, [x IN labels(c) WHERE x <> 'Node'][0] AS kind, coalesce(t.id, c.id) AS target, c.at AS at
ORDER BY target
LIMIT 20
