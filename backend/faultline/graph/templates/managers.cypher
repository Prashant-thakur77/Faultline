// id: Q-ORG-MGR
// purpose: the reporting chain (managers, ≤3 levels) of a set of people, for escalation
// seen: person, manager
MATCH (p:Person)-[:REPORTS_TO*1..3]->(m:Person)
WHERE p.id IN $ids AND m.active
RETURN p.id AS person, m.id AS manager
ORDER BY person, manager
LIMIT 100
