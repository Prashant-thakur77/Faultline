// id: Q-LEARN-SUGGESTS
// purpose: every exact fix (family, action kind, params hash) approved by a trusted person and verified APPLIED, with its count of distinct incidents (the learned-state panel lists those at or above $k as contract suggestions)
// home: oncall
// seen: events, incidents, family
// (one LIST grouping key: on 6.0.2 a single-node MATCH grouped by two properties returns the first aggregate in every
//  aggregate column, and a slice next to a count DISTINCT fails when ordered by a grouping key; docs/upstream/21)
MATCH (e:LearnEvent)
WHERE e.kind = 'verified' AND e.params_hash IS NOT NULL
WITH [e.family, e.action_kind, e.params_hash] AS fix, count(DISTINCT e.incident) AS n, collect(e.id) AS evs,
     collect(DISTINCT e.incident) AS incs, max(e.at) AS last_at, collect(DISTINCT e.person) AS people
WHERE n >= $k
WITH fix, n, evs[0..20] AS events, incs[0..20] AS incidents, last_at, people
RETURN fix[0] AS family, fix[1] AS action_kind, fix[2] AS params_hash, n, events, incidents, last_at, people
ORDER BY n DESC, family, action_kind, params_hash
LIMIT 50
