// id: Q-FIND-ID
// purpose: resolve a component by its id, ignoring case and hyphens ("productcatalog" → product-catalog); tier-1 seed alongside full-text
// seen: id
MATCH (n:Node)
WHERE (n:Service OR n:Datastore OR n:Table OR n:KPI OR n:Transform OR n:Dashboard OR n:Team)
  AND (n.id = $id OR replace(toLower(n.id), '-', '') = $norm)
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, coalesce(n.name, n.id) AS name, 'id' AS via
ORDER BY id
LIMIT 5
