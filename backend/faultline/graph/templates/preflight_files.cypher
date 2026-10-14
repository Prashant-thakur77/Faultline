// id: Q-PRE-3
// purpose: preflight: which component each changed file belongs to (files unknown to the graph raise uncertainty)
// seen: file, component
MATCH (f:File) WHERE f.id IN $files
OPTIONAL MATCH (f)-[:PART_OF]->(c)
RETURN f.id AS file, c.id AS component
ORDER BY file
LIMIT 100
