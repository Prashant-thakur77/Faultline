// id: Q-FLAGS-1
// purpose: feature flags with their state and the failure edge each one cuts (world model; seeds the simulated infra repo)
// seen: flag
MATCH (f:FeatureFlag)
RETURN f.id AS flag, f.state AS state, f.cuts_src AS cuts_src, f.cuts_dst AS cuts_dst
ORDER BY flag
LIMIT 50
