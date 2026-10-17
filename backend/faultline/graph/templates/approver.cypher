// id: Q-APPROVER-1
// purpose: who may approve an action on an incident (M19 fix: it now reads ON_CALL): an ACTIVE person who is on call (an ON_CALL shift overlapping $since to $now) for, or a member of, a team that OWNS an impacted component ($ids: the failing component, its blast radius and the symptoms); returns the team and component pairs that make them eligible, which the approval states as its reason
// returns: single-row
// seen: id
MATCH (p:Person {id:$person}) WHERE p.active
CALL { WITH p
       MATCH (p)-[oc:ON_CALL]->(t:Team)-[:OWNS]->(c:Node)
       WHERE oc.from <= $now AND $since < oc.to AND c.id IN $ids
       RETURN collect(DISTINCT [t.id, c.id]) AS oncall_owns }
CALL { WITH p
       MATCH (p)-[:MEMBER_OF]->(t:Team)-[:OWNS]->(c:Node)
       WHERE c.id IN $ids
       RETURN collect(DISTINCT [t.id, c.id]) AS member_owns }
RETURN p.id AS id, p.name AS name, p.role AS role, oncall_owns, member_owns,
       size(oncall_owns) + size(member_owns) > 0 AS eligible
LIMIT 1
