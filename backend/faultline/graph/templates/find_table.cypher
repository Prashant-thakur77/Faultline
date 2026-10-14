// id: Q-FIND-TABLE
// purpose: seed entities by name: full-text over Table.name
// seen: id
CALL db.idx.fulltext.queryNodes('Table', $text) YIELD node, score
RETURN node.id AS id, 'Table' AS label, score, 'fulltext' AS via
ORDER BY score DESC, id
LIMIT 10
