// id: Q-DEC-REV
// purpose: reversal guard: a change whose asserted fact is governed by a SUPERSEDED decision (the org decided this once and later reversed it), with the decision in force now (bounded SUPERSEDES walk to the active head) and what the head CITES (why it was reversed). Keys compare after the component segment, because the decision CONSTRAINS the very component the fact is ABOUT (preflight keys facts as <component id>.<key>, decisions may name the component by an alias). Whether the change actually reinstates the old rule is decided in code (agent/rules.py), as for Q-DEC-1. Annotation only: never a gate check, never a preflight score term. `because` lists the head's cited evidence, not the ADR records (doc-adr-*) themselves.
// seen: reversed, head
MATCH (src:Node {id:$change})-[:ASSERTS]->(f:ChangeFact)-[:ABOUT]->(n)<-[:CONSTRAINS]-(o:Decision)
WHERE o.status <> 'active' AND f.key IS NOT NULL AND o.rule_key IS NOT NULL
  AND (f.key = o.rule_key OR substring(f.key, size(split(f.key, '.')[0]) + 1) = substring(o.rule_key, size(split(o.rule_key, '.')[0]) + 1))
MATCH p = (o)<-[:SUPERSEDES*1..10]-(h:Decision {status:'active'})
WHERE NOT (h)<-[:SUPERSEDES]-(:Decision {status:'active'})
RETURN o.id AS reversed, o.title AS reversed_title, o.rule_key AS rule_key, o.rule_op AS op, o.rule_value AS old_value,
       o.decided_at AS reversed_decided_at, f.value AS actual, toString(f.value) AS actual_text, n.id AS about,
       h.id AS head, h.title AS head_title, h.decided_at AS head_decided_at, h.url AS head_url, length(p) AS hops,
       [(h)-[:CITES]->(x) WHERE NOT x.id STARTS WITH 'doc-adr-' | {id: x.id, title: x.title}] AS because
ORDER BY reversed, head, about
LIMIT 20
