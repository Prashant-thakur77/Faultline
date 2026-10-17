// id: Q-BOT-CHATS
// purpose: the Telegram chats linked to people ($person, or every chat when it is empty), newest link first: where a page to that person is delivered and where the morning digest goes
// home: oncall
// internal: true
// seen: id
MATCH (c:BotChat)
WHERE $person = '' OR c.person = $person
RETURN c.id AS id, c.chat AS chat, c.user AS user, c.person AS person, c.linked_at AS linked_at,
       c.muted_until AS muted_until
ORDER BY linked_at DESC, id
LIMIT 50
