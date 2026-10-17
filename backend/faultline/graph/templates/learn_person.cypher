// id: Q-LEARN-PERSON
// purpose: forget dry run (M21): every learning event a person contributed (keyset-paged on (at, id) after $after_at, $after_id), with what each one feeds (family, gap) and the guidelines it proposed, so the receipt lists exactly what will be deleted and recomputed
// home: oncall
// seen: id, guidelines
MATCH (e:LearnEvent)
WHERE e.person = $person AND (e.at > $after_at OR (e.at = $after_at AND e.id > $after_id))
RETURN e.id AS id, e.kind AS kind, e.family AS family, e.action_kind AS action_kind, e.at AS at, e.incident AS incident,
       e.gap AS gap, e.text AS text, e.about AS about, e.intent AS intent, e.reason AS reason,
       [(gd:Guideline)-[:DERIVED_FROM]->(e) | gd.id] AS guidelines
ORDER BY at, id
LIMIT 100
