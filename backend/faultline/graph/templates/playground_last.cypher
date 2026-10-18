// id: Q-PLAY-LAST
// purpose: break the graph: the latest recorded diff for one perturbation in the audit graph, so a public demo serves it instead of copying rooms again (and the diff is a FalkorDB record, not only an HTTP response)
// home: audit
// returns: single-row
// seen: kind
MATCH (r:PlaygroundRun {kind: $kind})
RETURN r.kind AS kind, r.result AS result, r.at AS at
ORDER BY at DESC
LIMIT 1
