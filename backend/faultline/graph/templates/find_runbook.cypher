// id: Q-FIND-RUNBOOK
// purpose: seed entities: full-text over Runbook.title (current runbooks only)
// seen: id
CALL db.idx.fulltext.queryNodes('Runbook', $text) YIELD node, score
WITH node, score WHERE node.valid_to IS NULL
RETURN node.id AS id, 'Runbook' AS label, score, 'fulltext' AS via
ORDER BY score DESC, id
LIMIT 10
