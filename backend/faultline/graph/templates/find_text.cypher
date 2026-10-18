// id: Q-FIND-TEXT
// purpose: seed entities by name in one query when no query embedding is available: full-text over Service/Table/Runbook/Decision names, one row per entity with its best score ($labels = [] for all labels)
// seen: id
CALL {
  UNWIND CASE WHEN size($labels) = 0 OR 'Service' IN $labels THEN [1] ELSE [] END AS one
  CALL db.idx.fulltext.queryNodes('Service', $text) YIELD node, score
  RETURN node.id AS id, 'Service' AS label, null AS status, score, 'fulltext' AS via
  ORDER BY score DESC, id
  LIMIT 10
  UNION ALL
  UNWIND CASE WHEN size($labels) = 0 OR 'Table' IN $labels THEN [1] ELSE [] END AS one
  CALL db.idx.fulltext.queryNodes('Table', $text) YIELD node, score
  RETURN node.id AS id, 'Table' AS label, null AS status, score, 'fulltext' AS via
  ORDER BY score DESC, id
  LIMIT 10
  UNION ALL
  UNWIND CASE WHEN size($labels) = 0 OR 'Runbook' IN $labels THEN [1] ELSE [] END AS one
  CALL db.idx.fulltext.queryNodes('Runbook', $text) YIELD node, score
  WITH node, score WHERE node.valid_to IS NULL
  RETURN node.id AS id, 'Runbook' AS label, null AS status, score, 'fulltext' AS via
  ORDER BY score DESC, id
  LIMIT 10
  UNION ALL
  UNWIND CASE WHEN size($labels) = 0 OR 'Decision' IN $labels THEN [1] ELSE [] END AS one
  CALL db.idx.fulltext.queryNodes('Decision', $text) YIELD node, score
  RETURN node.id AS id, 'Decision' AS label, node.status AS status, score, 'fulltext' AS via
  ORDER BY score DESC, id
  LIMIT 10
}
WITH id, head(collect(label)) AS label, head([s IN collect(status) WHERE s IS NOT NULL]) AS status,
     max(score) AS score, collect(DISTINCT via) AS via
RETURN id, label, status, score, CASE WHEN size(via) = 2 THEN ['fulltext', 'vector'] ELSE via END AS via
ORDER BY score DESC, id
LIMIT 20
