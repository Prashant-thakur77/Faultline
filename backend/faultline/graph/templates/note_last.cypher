// id: Q-NOTE-LAST
// purpose: the newest shared note an author wrote (a later step of the same agent run replies to it, so an investigation and its verified fix form one thread)
// home: agentmem
MATCH (a:Author {id: $principal})-[:WROTE]->(n:Note)
RETURN n.id AS id, n.created_at AS created_at
ORDER BY created_at DESC, id
LIMIT 1
