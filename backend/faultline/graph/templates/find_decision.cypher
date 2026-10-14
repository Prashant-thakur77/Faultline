// id: Q-FIND-DECISION
// purpose: seed entities: full-text over Decision.title
// seen: id
CALL db.idx.fulltext.queryNodes('Decision', $text) YIELD node, score
RETURN node.id AS id, 'Decision' AS label, node.status AS status, score, 'fulltext' AS via
ORDER BY score DESC, id
LIMIT 10
