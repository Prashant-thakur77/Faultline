// id: Q-PERSON-1
// purpose: an ACTIVE person in this tenant graph (who may name a fix, approve a learned edge or answer a contradicted decision; incident actions and standing contracts need Q-APPROVER-1)
// returns: single-row
// seen: id
MATCH (p:Person {id:$person}) WHERE p.active
RETURN p.id AS id, p.name AS name, p.role AS role
LIMIT 1
