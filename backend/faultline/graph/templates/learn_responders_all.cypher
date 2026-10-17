// id: Q-LEARN-RESPS
// purpose: every learned responder edge of the tenant (the learned-state panel): person, the family component, the decayed score at $now, the counts, mean ack delay, last response and the events
// home: oncall
// seen: person, family, events
MATCH (p:Person)-[r:RESPONDED]->(c:Node)
WITH p, r, c, exp(-0.6931471805599453 * toFloat($now - r.computed_at) / $half_life_ms) AS k
RETURN p.id AS person, p.name AS name, p.active AS active, c.id AS family, r.score * k AS score, r.n AS n,
       r.acks AS acks, r.approvals AS approvals, r.fixes AS fixes, r.mtta_ms AS mtta_ms, r.last_at AS last_at,
       r.incidents AS incidents, r.events AS events
ORDER BY score DESC, person, family
LIMIT 100
