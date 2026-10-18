// id: Q-NODE-EXISTS
// purpose: which of the given ids are nodes of this tenant's graph; a bound over a suspect that is not in the graph is unknown, never "insufficient" (the graph has nothing to say about it)
// seen: id
MATCH (n:Node) WHERE n.id IN $ids
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label
ORDER BY id
LIMIT 50
