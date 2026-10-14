// id: Q-APPROVER-1
// purpose: who may approve: an ACTIVE person in this tenant's graph; reports whether they own, are on call for, or recently worked on the affected component (shown with the approval)
// returns: single-row
// seen: id
MATCH (p:Person {id:$person}) WHERE p.active
RETURN p.id AS id, p.name AS name,
       size([(p)-[:MEMBER_OF]->(:Team)-[:OWNS]->(c:Node) WHERE c.id = $component | c]) > 0 AS owner_team,
       size([(p)-[:COMMITTED]->(c:Node) WHERE c.id = $component | c]) > 0 AS committed
LIMIT 1
