// id: Q-LEARN-RESP
// purpose: learned responders of one component: active people with a RESPONDED edge to it (recomputed from their trusted acks, approvals and verified fixes with recency decay), the score decayed again from computed_at to $now, the counts, the mean ack delay, the last response and the events it rests on
// home: oncall
// seen: person, events
MATCH (p:Person)-[r:RESPONDED]->(c:Node {id: $target})
WHERE p.active
WITH p, r, exp(-0.6931471805599453 * toFloat($now - r.computed_at) / $half_life_ms) AS k
RETURN p.id AS person, p.name AS name, r.score * k AS score, r.n AS n, r.acks AS acks, r.approvals AS approvals,
       r.fixes AS fixes, r.mtta_ms AS mtta_ms, r.last_at AS last_at, r.incidents AS incidents, r.events AS events
ORDER BY score DESC, person
LIMIT 20
