// id: Q-INTENT-1
// purpose: reconciler input: the PENDING intents it may take now, judged on the ENGINE clock (timestamp(), the clock that wrote created_at and lease_until; never a caller's clock): never leased and older than $grace_ms (a direct caller without a lease), or leased with the lease expired or held by a process boot that is no longer alive ($live: boots with a recent heartbeat in the audit graph; null = cannot tell, then only expiry counts); with their action and run, oldest first
// seen: incident, action
MATCH (i:Incident)-[:HAS_INTENT]->(it:Intent {state:'PENDING'})
MATCH (i)-[:HAS_PLAN]->(a:Action)
WHERE a.idem = it.idem
  AND ((it.lease_by IS NULL AND it.created_at < timestamp() - $grace_ms)
       OR (it.lease_by IS NOT NULL AND (coalesce(it.lease_until, 0) < timestamp()
           OR ($live IS NOT NULL AND it.lease_boot IS NOT NULL AND NOT it.lease_boot IN $live))))
RETURN i.id AS incident, it.idem AS idem, it.action_type AS kind, it.created_at AS created_at, it.created_by_run AS run,
       a.id AS action, a.status AS status, a.spec AS spec, a.external_ref AS external_ref, a.verdict AS verdict,
       a.kind AS action_kind, a.explanation AS explanation, i.stage AS stage, it.created_boot AS created_boot,
       it.lease_boot AS lease_boot, it.world AS world
ORDER BY created_at, idem
LIMIT 50
