// id: Q-ORG-BUS
// purpose: bus factor in the graph: the fewest ACTIVE people (most commits first) whose commits cover > 50% of the component's commits (0 = nobody active does), plus whether the top contributor has left
// returns: single-row
// seen: top_person
MATCH (s:Node {id:$target})<-[c:COMMITTED]-(p:Person)
WITH p, c ORDER BY c.n DESC, p.id
WITH collect({id: p.id, n: c.n, active: p.active}) AS rows, sum(c.n) AS total
WITH rows, total WHERE size(rows) > 0
WITH rows, total, [x IN rows WHERE x.active] AS act
WITH rows, total, act, [i IN range(0, size(act) - 1) WHERE reduce(acc = 0, x IN act[0..i + 1] | acc + x.n) * 2 > total] AS covering
RETURN total, CASE WHEN size(covering) = 0 THEN 0 ELSE covering[0] + 1 END AS bus_factor,
       rows[0].id AS top_person, NOT coalesce(rows[0].active, true) AS top_contributor_inactive, size(rows) AS committers
LIMIT 1
