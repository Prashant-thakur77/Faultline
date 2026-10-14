// id: Q-BRAIN-RUNS
// purpose: how many brain questions a graph has recorded since it was born (a public-mode brain scratch copy is stamped Meta.scratch_born on the engine clock when it is made, so runs copied over from the tenant graph do not count; it is replaced once it holds weights.yaml brain.scratch_max_runs runs)
// returns: single-row
MATCH (m:Meta)
MATCH (r:Run {mode: 'brain'}) WHERE r.created_at >= coalesce(m.scratch_born, 0)
RETURN count(r) AS runs
LIMIT 1
