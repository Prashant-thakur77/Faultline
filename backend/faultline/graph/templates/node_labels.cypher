// id: Q-LABELS-1
// purpose: the label of each given node id (the simulator attaches telemetry windows to components by label)
// seen: id
MATCH (n:Node) WHERE n.id IN $ids
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label
ORDER BY id
LIMIT 100
