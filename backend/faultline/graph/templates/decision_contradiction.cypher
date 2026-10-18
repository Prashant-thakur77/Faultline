// id: Q-DEC-1
// purpose: gate G8 / preflight: active, non-superseded decisions constraining what a change asserts about; with the reviewer override recorded for THIS change, if any (intentional / accidental / discuss); an override counts only while the change still asserts the value it was given for (a re-push with another value brings the violation back)
// seen: decision, about
MATCH (src:Node {id:$change})-[:ASSERTS]->(f:ChangeFact)-[:ABOUT]->(n)<-[:CONSTRAINS]-(d:Decision {status:'active'})
WHERE f.key = d.rule_key AND NOT (d)<-[:SUPERSEDES]-(:Decision {status:'active'})
RETURN d.id AS decision, d.title AS title, d.rule_key AS rule_key, d.rule_op AS op, d.rule_value AS expected,
       f.value AS actual, toString(f.value) AS actual_text, d.url AS url, n.id AS about,
       head([(d)<-[:OVERRIDES]-(o:Override) WHERE o.change_id = $change AND o.actual = toString(f.value) |
             {verdict: o.verdict, by: o.by, why: o.why, at: o.at}]) AS override
ORDER BY decision, about
LIMIT 20
