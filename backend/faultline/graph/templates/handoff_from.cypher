// id: Q-HANDOFF-FROM
// purpose: who hands off to $to: the active person on call at $now for a team $to belongs to (the outgoing shift), with that shift
// home: oncall
// seen: person
MATCH (t:Person {id:$to})-[:MEMBER_OF]->(team:Team)<-[oc:ON_CALL]-(f:Person)
WHERE oc.from <= $now AND $now < oc.to AND f.active AND f.id <> $to
RETURN f.id AS person, f.name AS name, team.id AS team, oc.from AS from, oc.to AS to
ORDER BY from DESC, person
LIMIT 1
