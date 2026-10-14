// id: Q-COUNT-2
// purpose: node counts per label of a tenant graph (tenant size facts for the eval report and the tenant switch)
// seen: label
MATCH (n:Node)
WITH [x IN labels(n) WHERE x <> 'Node'][0] AS label
RETURN label, count(*) AS n
ORDER BY label
LIMIT 100
