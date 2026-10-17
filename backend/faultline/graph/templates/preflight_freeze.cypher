// id: Q-PRE-FREEZE
// purpose: change-freeze policies in force on the components a PR changes, decided in the engine from the wall clock: the instant at (epoch ms; null means the engine clock) plus the policy fixed UTC offset becomes a local datetime, and its ISO weekday (dayOfWeek, Sunday read as 7), hour and minute are tested against the weekly window, which may wrap the week
// seen: component, policy
UNWIND $components AS cid
MATCH (p:Policy {kind:'change_freeze', status:'active'})-[:FREEZES]->(c:Node {id: cid})
WITH p, c, coalesce($at, timestamp()) AS at
WITH p, c, at, localdatetime('1970-01-01T00:00:00') + duration({seconds: toInteger(at / 1000) + p.utc_offset_min * 60}) AS t
WITH p, c, at, t, CASE WHEN t.dayOfWeek = 0 THEN 7 ELSE t.dayOfWeek END AS day
WITH p, c, at, t, day, (day - 1) * 1440 + t.hour * 60 + t.minute AS wm,
     (p.from_day - 1) * 1440 + p.from_hour * 60 AS ws, (p.to_day - 1) * 1440 + p.to_hour * 60 AS we
WHERE (ws <= we AND wm >= ws AND wm < we) OR (ws > we AND (wm >= ws OR wm < we))
RETURN c.id AS component, p.id AS policy, p.title AS title, p.effect AS effect, p.why AS why, p.url AS url,
       p.decided_by AS decided_by, at, toString(t) AS local_time, day, t.hour AS hour, t.minute AS minute,
       p.utc_offset_min AS utc_offset_min
ORDER BY component, policy
LIMIT 50
