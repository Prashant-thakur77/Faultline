// id: Q-ORG-2
// purpose: bus factor input: commit counts per person on a component (factor computed in code)
// seen: person
MATCH (s:Node {id:$target})<-[c:COMMITTED]-(p:Person)
RETURN p.id AS person, c.n AS n, p.active AS active, c.last_at AS last_at
ORDER BY n DESC, person
LIMIT 50
