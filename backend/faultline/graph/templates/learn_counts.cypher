// id: Q-LEARN-COUNTS
// purpose: how many learning events of each kind the tenant holds, from how many people, and the newest (the learned-state panel header)
// home: oncall
// seen: kind
MATCH (e:LearnEvent)
RETURN e.kind AS kind, count(e) AS n, count(DISTINCT e.person) AS people, max(e.at) AS last_at
ORDER BY kind
LIMIT 20
