// id: Q-PRE-HIST
// purpose: preflight backtest: merged PRs in merge order, one keyset page after ($after, $after_id), with the incidents their deploys caused (the backtest's labels, from graph history)
// seen: pr, caused
MATCH (p:PR)
WHERE p.merged_at IS NOT NULL AND (p.merged_at > $after OR (p.merged_at = $after AND p.id > $after_id))
WITH p, [(p)-[:CONTAINS]->(:Commit)<-[:CONTAINS]-(:Deploy)-[:CAUSED]->(i:Incident) | i.id] AS hits
RETURN p.id AS pr, p.merged_at AS merged_at, reduce(acc = [], x IN hits | CASE WHEN x IN acc THEN acc ELSE acc + [x] END) AS caused
ORDER BY merged_at, pr
LIMIT 100
