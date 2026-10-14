// id: Q-LEVER-1
// purpose: containment levers: feature flags whose "off" state cuts a given failure edge (u → v)
// seen: flag
MATCH (f:FeatureFlag)
WHERE f.cuts_src = $u AND f.cuts_dst = $v
RETURN f.id AS flag, f.state AS state, f.note AS note
ORDER BY flag
LIMIT 10
