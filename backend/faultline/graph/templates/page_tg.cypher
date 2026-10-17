// id: Q-PAGE-TG
// purpose: which Telegram message shows each page of an incident (chat, message id, digest of the card it shows), so the bot edits it in place; internal: never served to API or MCP readers
// home: oncall
// internal: true
// seen: id
MATCH (pg:Page)-[:FOR]->(i:Incident {id:$inc})
WHERE pg.tg_message_id IS NOT NULL
RETURN pg.id AS id, pg.tg_chat AS tg_chat, pg.tg_message_id AS tg_message_id, pg.tg_digest AS tg_digest
ORDER BY id
LIMIT 100
