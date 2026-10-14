// id: Q-ACT-1
// purpose: the plan of an incident: options, the chosen/approved/rejected action, verdicts
// seen: id, target
MATCH (i:Incident {id:$inc})-[:HAS_PLAN]->(a:Action)
RETURN a.id AS id, a.kind AS kind, a.option AS option, a.enabled AS enabled, a.reason AS reason, a.target_id AS target,
       a.status AS status, a.preview AS preview, a.spec AS spec, a.plan_hash AS plan_hash, a.idem AS idem,
       a.external_ref AS external_ref, a.verdict AS verdict, a.explanation AS explanation, a.channels AS channels,
       a.approval_id AS approval_id, a.rejected_by AS rejected_by, a.reject_reason AS reject_reason,
       a.rejected_at AS rejected_at, a.future AS future
ORDER BY id
LIMIT 20
