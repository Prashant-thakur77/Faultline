// id: Q-BOT-PROPOSAL
// purpose: the open typed-phrase consents of one Telegram chat whose hash starts with the typed code (approve or grant), unexpired at $now, newest first
// home: oncall
// internal: true
// seen: id
MATCH (p:BotProposal)
WHERE p.chat = $chat AND p.kind = $kind AND p.prefix = $prefix AND p.status = 'open' AND p.expires_at > $now
RETURN p.id AS id, p.user AS user, p.person AS person, p.tenant AS tenant, p.graph AS graph, p.incident AS incident,
       p.action AS action, p.hash AS hash, p.expires_at AS expires_at, p.detail AS detail
ORDER BY expires_at DESC, id
LIMIT 5
