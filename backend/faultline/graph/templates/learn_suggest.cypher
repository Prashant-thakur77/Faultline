// id: Q-LEARN-SUGGEST
// purpose: contract suggestions (M21): for one family, every exact fix (action kind + params hash) a trusted person approved that was then verified APPLIED, on how many distinct incidents, when last and by whom; only those reaching $k (weights.yaml learn.contract_suggest_k). The plan then offers the M19 two-step grant; it never grants
// home: oncall
// seen: events, incidents
// (one LIST grouping key: on 6.0.2 a single-node MATCH grouped by two properties returns the first aggregate in every
//  aggregate column, and a slice next to a count DISTINCT fails when ordered by a grouping key; docs/upstream/21)
MATCH (e:LearnEvent)
WHERE e.kind = 'verified' AND e.family = $family AND e.params_hash IS NOT NULL
WITH [e.action_kind, e.params_hash] AS fix, count(DISTINCT e.incident) AS n, collect(e.id) AS evs,
     collect(DISTINCT e.incident) AS incs, max(e.at) AS last_at, collect(DISTINCT e.person) AS people
WHERE n >= $k
WITH fix, n, evs[0..20] AS events, incs[0..20] AS incidents, last_at, people
RETURN fix[0] AS action_kind, fix[1] AS params_hash, n, events, incidents, last_at, people
ORDER BY n DESC, action_kind, params_hash
LIMIT 20
