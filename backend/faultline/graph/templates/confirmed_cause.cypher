// id: Q-CAUSE-1
// purpose: the cause the gate confirmed for an incident (the confirmed Hypothesis), newest first
// seen: cause
MATCH (i:Incident {id:$inc})-[:HYPOTHESIZES]->(h:Hypothesis {status:'confirmed'})
RETURN h.cause_id AS cause, h.updated_at AS at
ORDER BY at DESC, cause
LIMIT 1
