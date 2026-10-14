// id: Q-DEC-ONE
// purpose: one decision of Q-DEC-1 for one change (the override endpoint: filtered in the query, so a change asserting many facts never hides it behind the LIMIT)
// seen: decision, about
MATCH (src:Node {id:$change})-[:ASSERTS]->(f:ChangeFact)-[:ABOUT]->(n)<-[:CONSTRAINS]-(d:Decision {status:'active'})
WHERE d.id = $decision AND f.key = d.rule_key AND NOT (d)<-[:SUPERSEDES]-(:Decision {status:'active'})
RETURN d.id AS decision, d.title AS title, d.rule_key AS rule_key, d.rule_op AS op, d.rule_value AS expected,
       f.value AS actual, toString(f.value) AS actual_text, d.url AS url, n.id AS about,
       head([(d)<-[:OVERRIDES]-(o:Override) WHERE o.change_id = $change AND o.actual = toString(f.value) |
             {verdict: o.verdict, by: o.by, why: o.why, at: o.at}]) AS override
ORDER BY decision, about
LIMIT 20
