// id: Q-DEC-KEYS
// purpose: preflight code facts: the rule keys decisions (any status) set on these components, the vocabulary a changed code constant's name is matched against so it asserts the same key a config edit would
// seen: about
MATCH (d:Decision)-[:CONSTRAINS]->(n:Node)
WHERE n.id IN $ids AND d.rule_key IS NOT NULL
RETURN n.id AS about, collect(DISTINCT d.rule_key) AS keys
ORDER BY about
LIMIT 100
