// id: Q-HYP-1
// purpose: hypotheses of an incident with the evidence that supports/refutes them (gate G6, UI)
// seen: cause
MATCH (i:Incident {id:$inc})-[:HYPOTHESIZES]->(h:Hypothesis)-[:BLAMES]->(c:Node)
OPTIONAL MATCH (e:Evidence)-[:SUPPORTS]->(h)
OPTIONAL MATCH (e2:Evidence)-[:REFUTES]->(h)
RETURN h.id AS id, c.id AS cause, h.status AS status, h.score AS score, h.reason AS reason, h.origin AS origin,
       coalesce(h.status_by, h.origin) AS status_by,
       collect(DISTINCT e.id) AS supports, collect(DISTINCT e2.id) AS refutes
ORDER BY id
LIMIT 50
