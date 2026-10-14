// id: Q-OWN-AT
// purpose: ownership over time: every OWNED_AT period of a component, which one covered time $at, and which is current
// seen: team
MATCH (t:Team)-[o:OWNED_AT]->(n:Node {id: $id})
RETURN t.id AS team, t.name AS name, o.from AS since, o.to AS until,
       (o.from <= $at AND (o.to IS NULL OR $at < o.to)) AS covers_at,
       o.to IS NULL AS current
ORDER BY since, team
LIMIT 20
