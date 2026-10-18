// id: Q-DOC-URLS
// purpose: the documents of a graph and the files they point at (seed-time chunking of document text, ingest/chunks.py)
MATCH (d:Doc)
WHERE d.url IS NOT NULL
RETURN d.id AS id, d.url AS url
ORDER BY id
LIMIT 100
