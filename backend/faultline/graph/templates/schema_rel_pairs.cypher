// id: Q-SCHEMA-2
// purpose: schema introspection: the (from-label, to-label) endpoint pairs of every relationship type, with counts, over a bounded edge scan (first 100000 edges; complete when the sampled total equals Q-SCHEMA-1 relCount)
MATCH (a)-[r]->(b)
WITH a, r, b LIMIT 100000
WITH type(r) AS type, [x IN labels(a) WHERE x <> 'Node'][0] AS src, [x IN labels(b) WHERE x <> 'Node'][0] AS dst, count(*) AS n
ORDER BY type, src, dst
WITH type, collect({src: src, dst: dst, n: n}) AS pairs, toInteger(sum(n)) AS sampled
RETURN type, pairs, sampled
ORDER BY type
LIMIT 100
