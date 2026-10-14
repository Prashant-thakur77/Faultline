// id: Q-BOOT-LIVE
// purpose: process boots alive now on the engine clock (audit graph): a heartbeat within $stale_ms and not ended; an intent lease held by any other boot belongs to a dead process and may be taken over at once
// returns: rows
MATCH (b:Boot)
WHERE b.ended_at IS NULL AND b.seen_at >= timestamp() - $stale_ms
RETURN b.id AS boot, b.seen_at AS seen_at, b.role AS role
ORDER BY boot
LIMIT 100
