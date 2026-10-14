// id: Q-SCHEMA-3
// purpose: schema introspection: property keys per label with how many sampled nodes carry each, over a bounded node scan (first 20000 nodes; complete when the sampled total equals Q-SCHEMA-1 nodeCount)
MATCH (n)
WITH n LIMIT 20000
WITH [x IN labels(n) WHERE x <> 'Node'][0] AS label, keys(n) AS ks
WITH label, count(*) AS sampled, collect(ks) AS kss
UNWIND kss AS kl
UNWIND kl AS key
WITH label, sampled, key, count(*) AS c
ORDER BY label, key
WITH label, sampled, collect({key: key, n: c}) AS keys
RETURN label, sampled, keys
ORDER BY label
LIMIT 100
