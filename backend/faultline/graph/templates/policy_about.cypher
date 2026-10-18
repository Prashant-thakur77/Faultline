// id: Q-POLICY-ABOUT
// purpose: the policies that govern a component (a change freeze FREEZES it, or any other policy relationship to it), who decided each, and whether each person is still active; answers "who put the freeze on X in place?"
// seen: policy, person
MATCH (pol:Policy)-->(n:Node {id: $id})
OPTIONAL MATCH (p:Person)-[:DECIDED]->(pol)
RETURN pol.id AS policy, pol.title AS title, pol.status AS status, pol.decided_at AS decided_at, pol.url AS url,
       p.id AS person, p.name AS name, coalesce(p.active, false) AS active
ORDER BY decided_at DESC, policy, person
LIMIT 20
