// id: Q-DEC-3
// purpose: sources a decision cites (provenance for answers)
// returns: single-row
// seen: id, source_ids
MATCH (d:Decision {id:$id})
OPTIONAL MATCH (d)-[:CITES]->(src)
RETURN d.id AS id, d.status AS status, d.title AS title, collect(DISTINCT src.url) AS sources, collect(DISTINCT src.id) AS source_ids
LIMIT 1
