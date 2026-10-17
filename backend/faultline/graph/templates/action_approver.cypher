// id: Q-ACT-APPROVER
// purpose: how an approved action ended and who approved it: the incident stage, the action verdict and explanation, and the approver on its Approval (a person, or contract:<id> for a standing approval); read after the execute job or the reconciler to decide whether a human must be paged
// returns: single-row
// seen: approver
MATCH (i:Incident {id:$inc})-[:HAS_PLAN]->(a:Action {id:$aid})
MATCH (ap:Approval) WHERE ap.id = a.approval_id
RETURN i.stage AS stage, a.kind AS kind, a.option AS option, a.status AS status, a.verdict AS verdict,
       a.explanation AS explanation, ap.approver_id AS approver, ap.at AS approved_at
LIMIT 1
