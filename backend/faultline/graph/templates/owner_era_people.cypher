// id: Q-OWN-PEOPLE
// purpose: who carried the knowledge in an ownership era: people who were members of team $team during [$since, $until) and committed to the component, with whether they are still active
// seen: person
MATCH (p:Person)-[c:COMMITTED]->(n:Node {id: $id}), (p)-[m:MEMBER_OF]->(t:Team {id: $team})
WHERE m.from < $until AND (m.to IS NULL OR m.to > $since)
RETURN p.id AS person, p.name AS name, p.active AS active, c.n AS commits, c.last_at AS last_at,
       [(p)-[:MEMBER_OF]->(now:Team) WHERE now.id <> $team | now.id] AS other_teams
ORDER BY commits DESC, person
LIMIT 10
