// id: Q-BOT-CHAT
// purpose: one Telegram chat the on-call bot knows: the person it is linked to and until when its information notices are muted
// home: oncall
// internal: true
// returns: single-row
// seen: id
MATCH (c:BotChat {id:$id})
RETURN c.id AS id, c.chat AS chat, c.user AS user, c.person AS person, c.linked_at AS linked_at,
       c.muted_until AS muted_until
LIMIT 1
