// id: Q-CONTEND-1
// purpose: contention eval (evals/contention.py): for one incident, how many of its actions carry an approval, how many intents exist across its actions (an intent is MERGEd on the action's idempotency key) and how many Operator crew steps the run recorded (anchored matches only: an unanchored pattern comprehension returns [] on 6.0.2)
// returns: single-row
MATCH (r:Run {id: $run})
WITH size([(r)-[:HAS_TASK]->(t:Task) WHERE t.role = 'operator' | t.id]) AS operator_steps
MATCH (i:Incident {id: $inc})-[:HAS_PLAN]->(a:Action)
OPTIONAL MATCH (x:Intent) WHERE x.idem = a.idem   // lint: optional-where-ok (an action with no intent yet keeps its row)
RETURN count(DISTINCT CASE WHEN a.approval_id IS NOT NULL THEN a.id END) AS approved_actions,
       count(DISTINCT x) AS intents, max(operator_steps) AS operator_steps
LIMIT 1
