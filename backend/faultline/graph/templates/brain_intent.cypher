// id: Q-BRAIN-INTENT
// purpose: company-brain question routing, decided in the engine: the question's full-text matches over IntentExemplar.text (summed per kind, relative to the best kind) fused with its nearest IntentExemplar nodes by meaning (vector index, cosine; the nearest exemplar per kind), one row per question kind ranked by vsim + $w_ft × ft_rel. `answerable` = the kind's nearest exemplar is at least $min_sim similar AND the kind is not a refusal kind; the caller routes on the first row only, and refuses when it is not answerable
CALL db.idx.fulltext.queryNodes('IntentExemplar', $text) YIELD node, score
WITH node.intent AS intent, sum(score) AS fts
WITH collect({intent: intent, fts: fts}) AS ft
WITH ft, reduce(m = 0.0, x IN ft | CASE WHEN x.fts > m THEN x.fts ELSE m END) AS ftmax
CALL db.idx.vector.queryNodes('IntentExemplar', 'embedding', $k, vecf32($q)) YIELD node, score
WITH ft, ftmax, node, 1.0 - score AS sim
ORDER BY sim DESC, node.id
WITH ft, ftmax, node.intent AS intent, collect(node) AS near, max(sim) AS vsim
WITH intent, vsim, near[0] AS best, ftmax,
     reduce(s = 0.0, x IN ft | s + CASE WHEN x.intent = intent THEN x.fts ELSE 0.0 END) AS fts
WITH intent, vsim, best, fts, CASE WHEN ftmax > 0 THEN fts / ftmax ELSE 0.0 END AS ft_rel
RETURN intent, vsim, fts, ft_rel, vsim + $w_ft * ft_rel AS score, coalesce(best.refuse, false) AS refuse,
       best.id AS nearest, best.text AS nearest_text, (vsim >= $min_sim AND NOT coalesce(best.refuse, false)) AS answerable
ORDER BY score DESC, intent
LIMIT 20
