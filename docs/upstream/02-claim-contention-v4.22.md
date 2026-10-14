# Conditional MERGE claim yields two owners under 16-way contention (v4.22.0)

**Image:** v4.22.0 (digest above). 6.0.2 (sha256:107455e8…) passes 10/10 rounds.

Sixteen threads per round, released together by a barrier, each run:
```
MERGE (t:Task {id:$task}) ON CREATE SET t.state='open'
WITH t WHERE t.state = 'open' SET t.state='claimed', t.owner=$agent
WITH t MATCH (a:Agent {id:$agent}) MERGE (t)-[:CLAIMED_BY]->(a) RETURN t.owner
```
**Expected:** exactly one row returned per round and exactly one `CLAIMED_BY` edge.
**Actual (v4.22.0):** in 1 of 10 rounds two claimers returned a row (two owners). The script is `backend/faultline/graph/smoke/runner.py::p_concurrency`.
