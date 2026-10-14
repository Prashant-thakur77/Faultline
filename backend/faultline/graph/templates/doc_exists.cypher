// id: Q-DOC-1
// purpose: a document and what it produced (forget UI and receipts)
// returns: single-row
// seen: id, produced
MATCH (d:Doc {id:$doc})
RETURN d.id AS id, d.title AS title, d.kind AS kind, d.url AS url, [(d)-[:PRODUCED]->(n) | n.id] AS produced
LIMIT 1
