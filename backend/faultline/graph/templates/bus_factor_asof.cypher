// id: Q-ORG-BUS-ASOF
// purpose: preflight backtest: Q-ORG-BUS as of $as_of: commits authored before it (per person, on the component's files) and who was a team member then (MEMBER_OF window; people with no membership keep their active flag)
// returns: single-row
// seen: top_person
MATCH (s:Node {id:$target})<-[:PART_OF]-(:File)<-[:TOUCHES]-(k:Commit)<-[:AUTHORED]-(p:Person)
WHERE k.at < $as_of
WITH p, count(DISTINCT k) AS n
WITH p, n, [(p)-[m:MEMBER_OF]->(:Team) | {from: m.from, to: m.to}] AS ms
WITH p, n, CASE WHEN size(ms) = 0 THEN p.active
                ELSE size([m IN ms WHERE coalesce(m.from, 0) <= $as_of AND (m.to IS NULL OR m.to > $as_of)]) > 0 END AS active
ORDER BY n DESC, p.id
WITH collect({id: p.id, n: n, active: active}) AS rows, sum(n) AS total
WITH rows, total WHERE size(rows) > 0
WITH rows, total, [x IN rows WHERE x.active] AS act
WITH rows, total, act, [i IN range(0, size(act) - 1) WHERE reduce(acc = 0, x IN act[0..i + 1] | acc + x.n) * 2 > total] AS covering
RETURN total, CASE WHEN size(covering) = 0 THEN 0 ELSE covering[0] + 1 END AS bus_factor,
       rows[0].id AS top_person, NOT coalesce(rows[0].active, true) AS top_contributor_inactive, size(rows) AS committers
LIMIT 1
