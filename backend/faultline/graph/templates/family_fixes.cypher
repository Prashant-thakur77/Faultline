// id: Q-MEM-7
// purpose: what fixed a family: APPLIED actions by kind and target across the family's incidents (consolidation input)
// seen: incidents
MATCH (i:Incident)-[:RESOLVED_BY]->(a:Action)
WHERE i.id IN $members AND a.verdict = 'APPLIED'
RETURN a.kind AS kind, a.target_id AS target, count(DISTINCT i) AS n, collect(DISTINCT i.id) AS incidents
ORDER BY n DESC, kind, target
LIMIT 10
