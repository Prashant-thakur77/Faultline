// id: Q-META-1
// purpose: parking pattern: is this graph fully seeded? (Meta.ready), plus its content epoch (set by re-arm and an operator's forget; a brain scratch copy whose epoch differs from its tenant graph's is stale)
// returns: single-row
MATCH (m:Meta)
RETURN m.ready AS ready, m.data_hash AS data_hash, m.seeded_at AS seeded_at, m.engine AS engine, m.epoch AS epoch,
       m.scratch_born AS scratch_born
LIMIT 1
