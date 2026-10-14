// id: Q-PRE-2-ASOF
// purpose: preflight backtest: Q-PRE-2 as of $as_of (epoch ms): incidents opened before it, the owning team then (OWNED_AT window), runbooks valid then; no future leaks in
// seen: changed, team, past_incidents
MATCH (pr:PR {id:$pr})-[:TOUCHES]->(:File)-[:PART_OF]->(s)
WITH DISTINCT s
WITH s, [(s)<-[w:OWNED_AT]-(t:Team) | {team: t.id, from: w.from, to: w.to}] AS owned
RETURN s.id AS changed, [x IN labels(s) WHERE x <> 'Node'][0] AS label,
       [(s)<-[:CHANGED]-(:Deploy)-[:CAUSED]->(i:Incident) WHERE coalesce(i.opened_at, i.onset_at) < $as_of | i.id] AS past_incidents,
       [o IN owned WHERE coalesce(o.from, 0) <= $as_of AND (o.to IS NULL OR o.to > $as_of) | o.team] AS team,
       [(r:Runbook)-[:RUNBOOK_FOR]->(s) WHERE coalesce(r.valid_from, 0) <= $as_of AND (r.valid_to IS NULL OR r.valid_to > $as_of) | r.id] AS runbooks
ORDER BY changed
LIMIT 20
