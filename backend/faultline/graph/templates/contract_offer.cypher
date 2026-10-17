// id: Q-CONTRACT-OFFER
// purpose: one contract (offered or granted) by id: its status, hash, scope, the offer deadline and the incident and action it was offered from (step 2 of a grant checks these)
// home: oncall
// internal: true
// returns: single-row
// seen: id
MATCH (c:Contract {id:$id})
RETURN c.id AS id, c.status AS status, c.hash AS hash, c.family AS family, c.action_kind AS action_kind,
       c.params_hash AS params_hash, c.max_uses AS max_uses, c.expires_at AS expires_at,
       c.offer_expires_at AS offer_expires_at, c.covers AS covers, c.source_incident AS source_incident,
       c.source_graph AS source_graph, c.source_action AS source_action
LIMIT 1
