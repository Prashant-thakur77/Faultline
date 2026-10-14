// id: Q-CONTRAST-VEC
// purpose: contrast only, never a decision: rank the given changes by cosine distance between their title embedding and the incident's own embedding ("embeddings find"; eval arm V and docs/NAIVE_VS_FAULTLINE.md)
MATCH (i:Incident {id:$inc})
MATCH (d:Deploy)
WHERE d.id IN $ids AND d.embedding IS NOT NULL AND i.embedding IS NOT NULL
RETURN d.id AS change, d.title AS title, vec.cosineDistance(i.embedding, d.embedding) AS distance
ORDER BY distance, change
LIMIT 50
