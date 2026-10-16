// id: Q-BRAIN-INTENT-FT
// purpose: company-brain question routing by full-text only, used when the embedding model cannot load (the route says so): IntentExemplar.text matches summed per question kind; `answerable` = the summed score reaches $min_ft AND the kind is not a refusal kind
CALL db.idx.fulltext.queryNodes('IntentExemplar', $text) YIELD node, score
WITH node, score
ORDER BY score DESC, node.id
WITH node.intent AS intent, collect(node) AS near, sum(score) AS fts
WITH intent, fts, near[0] AS best
RETURN intent, null AS vsim, fts, null AS ft_rel, fts AS score, coalesce(best.refuse, false) AS refuse, best.id AS nearest,
       best.text AS nearest_text, (fts >= $min_ft AND NOT coalesce(best.refuse, false)) AS answerable
ORDER BY score DESC, intent
LIMIT 20
