// id: Q-PRE-FACTS
// purpose: the ChangeFacts a PR asserts (preflight deep links / receipts)
// seen: about
MATCH (pr:PR {id:$pr})-[:ASSERTS]->(f:ChangeFact)-[:ABOUT]->(n)
RETURN f.key AS key, f.value AS value, n.id AS about, f.file_id AS file
ORDER BY key
LIMIT 50
