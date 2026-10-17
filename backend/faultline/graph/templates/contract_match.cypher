// id: Q-CONTRACT-MATCH
// purpose: the standing approval that covers exactly this plan: an active Contract with the same family (the gate-confirmed origin component), action kind and params hash, uses below max_uses, not expired at $now, granted by a person who is still active; the oldest grant first
// home: oncall
// returns: single-row
// seen: id
MATCH (c:Contract)-[:GRANTED_BY]->(p:Person)
WHERE c.status = 'active' AND c.family = $family AND c.action_kind = $kind AND c.params_hash = $params_hash
  AND c.uses < c.max_uses AND c.expires_at > $now AND p.active
RETURN c.id AS id, c.family AS family, c.action_kind AS action_kind, c.params_hash AS params_hash, c.uses AS uses,
       c.max_uses AS max_uses, c.expires_at AS expires_at, c.granted_at AS granted_at, c.quote AS quote,
       p.id AS granted_by, p.name AS granted_by_name, coalesce(c.real_ok, false) AS real_ok
ORDER BY granted_at, id
LIMIT 1
