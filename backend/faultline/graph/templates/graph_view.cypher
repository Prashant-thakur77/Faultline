// id: Q-VIEW-1
// purpose: the failure-flow graph for the UI (services, datastores, data lineage); edges carry cap/domain
// seen: src, dst
MATCH (a:Node)-[r:PROPAGATES_TO]->(b:Node)
WHERE NOT a:Transform AND NOT b:Transform
RETURN a.id AS src, [x IN labels(a) WHERE x <> 'Node'][0] AS src_label, b.id AS dst, [x IN labels(b) WHERE x <> 'Node'][0] AS dst_label,
       r.cap AS cap, r.domain AS domain, coalesce(a.tier, 3) AS src_tier, coalesce(b.tier, 3) AS dst_tier
ORDER BY src, dst
LIMIT 100
