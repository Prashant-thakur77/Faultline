// id: Q-EV-1
// purpose: cited evidence with its provenance (template, Cypher, source, digest) and what it is ABOUT
// seen: about
MATCH (e:Evidence) WHERE e.id IN $ids
OPTIONAL MATCH (e)-[:ABOUT]->(n:Node)
WITH e, collect(DISTINCT n.id) AS about
RETURN e.id AS id, e.kind AS kind, e.source AS source, e.tool AS tool, e.template AS template, e.cypher AS cypher,
       e.summary AS summary, e.digest AS digest, e.value AS value, e.baseline AS baseline, e.anomalous AS anomalous, about
ORDER BY id
LIMIT 100
