// id: Q-ACT-INTENT
// purpose: execute preconditions: the action, its approval-bound plan hash and spec, and the intent's state, owner run and lease (lease_live on the engine clock: an expired lease fences the holder off before it touches the outside world)
// returns: single-row
// seen: id
MATCH (i:Incident {id:$inc})-[:HAS_PLAN]->(a:Action {id:$aid})
MATCH (it:Intent) WHERE it.idem = a.idem
RETURN a.id AS id, a.status AS status, a.plan_hash AS plan_hash, a.spec AS spec, a.kind AS kind,
       it.state AS intent_state, it.created_by_run AS intent_run, it.lease_by AS lease_by,
       coalesce(it.lease_until, 0) >= timestamp() AS lease_live, it.lease_boot AS lease_boot, i.stage AS stage
LIMIT 1
