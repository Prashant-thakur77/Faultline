// id: Q-FIND-SERVICE
// purpose: seed entities by name: full-text over Service.name (tier 1 of the brain/agent tools)
// seen: id
CALL db.idx.fulltext.queryNodes('Service', $text) YIELD node, score
RETURN node.id AS id, 'Service' AS label, score, 'fulltext' AS via
ORDER BY score DESC, id
LIMIT 10
