// id: Q-KNOW-1
// purpose: company-brain knowledge search (T3) in ONE query: what the organisation's documents say. Seven ranked lists, each from a FalkorDB index (vecf32 over Doc text chunks, credited to every decision or runbook the document produced, the best-ranked passage kept, postmortem summaries and runbooks with cosine at least $floor; full-text over chunks, postmortems, runbooks and decision titles), fused by reciprocal rank inside the engine (each list adds 1/($k + rank) for its best hit of a source), then expanded one and two hops: what each source is about, produced, constrains or documents, and who decided it
// seen: id, related
CALL {
  UNWIND CASE WHEN $q IS NULL THEN [] ELSE [1] END AS one
  CALL db.idx.vector.queryNodes('Chunk', 'embedding', 20, vecf32($q)) YIELD node, score
  WITH node, score WHERE 1.0 - score >= $floor
  WITH node, score ORDER BY score, node.id
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i
  MATCH (n)-[:PART_OF]->(d:Doc)
  WITH d, i, n, [(d)-[:PRODUCED]->(p) | p] AS produced
  UNWIND CASE WHEN size(produced) = 0 THEN [d] ELSE produced END AS src
  WITH src, i, n ORDER BY i
  WITH src, min(i) AS i, head(collect(n.text)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'vector' AS via
  UNION ALL
  UNWIND CASE WHEN $text = '' THEN [] ELSE [1] END AS one
  CALL db.idx.fulltext.queryNodes('Chunk', $text) YIELD node, score
  WITH node, score ORDER BY score DESC, node.id LIMIT 20
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i
  MATCH (n)-[:PART_OF]->(d:Doc)
  WITH d, i, n, [(d)-[:PRODUCED]->(p) | p] AS produced
  UNWIND CASE WHEN size(produced) = 0 THEN [d] ELSE produced END AS src
  WITH src, i, n ORDER BY i
  WITH src, min(i) AS i, head(collect(n.text)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'fulltext' AS via
  UNION ALL
  UNWIND CASE WHEN $q IS NULL THEN [] ELSE [1] END AS one
  CALL db.idx.vector.queryNodes('Postmortem', 'embedding', 20, vecf32($q)) YIELD node, score
  WITH node, score WHERE 1.0 - score >= $floor
  WITH node, score ORDER BY score, node.id
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i ORDER BY i
  WITH n AS src, min(i) AS i, head(collect(n.summary)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'vector' AS via
  UNION ALL
  UNWIND CASE WHEN $text = '' THEN [] ELSE [1] END AS one
  CALL db.idx.fulltext.queryNodes('Postmortem', $text) YIELD node, score
  WITH node, score ORDER BY score DESC, node.id LIMIT 20
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i ORDER BY i
  WITH n AS src, min(i) AS i, head(collect(n.summary)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'fulltext' AS via
  UNION ALL
  UNWIND CASE WHEN $q IS NULL THEN [] ELSE [1] END AS one
  CALL db.idx.vector.queryNodes('Runbook', 'embedding', 20, vecf32($q)) YIELD node, score
  WITH node, score WHERE 1.0 - score >= $floor
  WITH node, score ORDER BY score, node.id
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i ORDER BY i
  WITH n AS src, min(i) AS i, head(collect(n.title)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'vector' AS via
  UNION ALL
  UNWIND CASE WHEN $text = '' THEN [] ELSE [1] END AS one
  CALL db.idx.fulltext.queryNodes('Runbook', $text) YIELD node, score
  WITH node, score ORDER BY score DESC, node.id LIMIT 20
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i ORDER BY i
  WITH n AS src, min(i) AS i, head(collect(n.title)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'fulltext' AS via
  UNION ALL
  UNWIND CASE WHEN $text = '' THEN [] ELSE [1] END AS one
  CALL db.idx.fulltext.queryNodes('Decision', $text) YIELD node, score
  WITH node, score ORDER BY score DESC, node.id LIMIT 20
  WITH collect(node) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  WITH hits[i] AS n, i ORDER BY i
  WITH n AS src, min(i) AS i, head(collect(n.title)) AS snippet
  RETURN src, snippet, 1.0 / ($k + i + 1) AS rrf, 'fulltext' AS via
}
WITH src, rrf, snippet, via ORDER BY rrf DESC
WITH src, sum(rrf) AS score, collect(DISTINCT via) AS via, head(collect(snippet)) AS snippet
RETURN src.id AS id, [x IN labels(src) WHERE x <> 'Node'][0] AS label, coalesce(src.title, src.summary) AS title,
       src.kind AS kind, faultline.round4(score) AS score, CASE WHEN size(via) = 2 THEN ['fulltext', 'vector'] ELSE via END AS via,
       snippet,
       [(src)-[:ABOUT|PRODUCED|CONSTRAINS|RUNBOOK_FOR|DOCUMENTS|CITES]->(x) | x.id]
         + [(src)-[:PRODUCED]->()-[:CONSTRAINS|RUNBOOK_FOR]->(y) | y.id]
         + [(p:Person)-[:DECIDED]->(src) | p.id] AS related
ORDER BY score DESC, id
LIMIT 8
