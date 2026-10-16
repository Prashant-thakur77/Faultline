// id: Q-BRAIN-VOCAB
// purpose: which of a question's words are how brain questions are ASKED rather than what they are about: the words that occur (stemmed, full-text index) in an answerable IntentExemplar text ("feature", "flags", "dashboards"). Entity resolution still tries every word as an exact id, but never fuzzy- or full-text-matches these to a component
UNWIND $words AS w
CALL db.idx.fulltext.queryNodes('IntentExemplar', w) YIELD node
WITH w, node
WHERE NOT coalesce(node.refuse, false)
WITH w, count(node) AS n
RETURN w AS word, n
ORDER BY word
LIMIT 50
