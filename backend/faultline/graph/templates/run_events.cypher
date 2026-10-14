// id: Q-RUN-1
// purpose: the run timeline (stage events) for SSE and the replay export
MATCH (run:Run {id:$run})-[:HAS_STAGE]->(se:StageEvent)
RETURN se.id AS id, se.stage AS stage, se.ord AS ord, se.at AS at, se.note AS note
ORDER BY at, ord, id
LIMIT 100
