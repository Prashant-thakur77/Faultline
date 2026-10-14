// id: Q-RUN-TOKEN
// purpose: public demo capability check: the stored hash of a run's token (choose/approve require the matching token)
// returns: single-row
MATCH (run:Run {id:$run})
RETURN run.token_sha AS token_sha
LIMIT 1
