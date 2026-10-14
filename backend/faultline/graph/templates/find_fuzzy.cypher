// id: Q-FIND-FUZZY
// purpose: fuzzy entity resolution inside the engine (FalkorDB FLEX flex.text.jaroWinkler) when no id matches exactly: a misspelling like "pyment" resolves to payment, with its similarity. A length-ratio and first-letter guard keeps a generic prefix ("audit" vs audit-log) from resolving
// seen: id
MATCH (n:Node)
WHERE n:Service OR n:Datastore OR n:Table OR n:KPI OR n:Transform OR n:Dashboard OR n:Team
WITH n, replace(toLower(n.id), '-', '') AS nid
WHERE left(nid, 1) = left($norm, 1)
  AND toFloat(size(nid)) >= $ratio * size($norm) AND toFloat(size($norm)) >= $ratio * size(nid)
WITH n, flex.text.jaroWinkler(nid, $norm) AS sim
WHERE sim >= $min
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, coalesce(n.name, n.id) AS name, sim, 'fuzzy' AS via
ORDER BY sim DESC, id
LIMIT 5
