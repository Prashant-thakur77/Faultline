// id: Q-GC-HOLD
// purpose: why the live collector must keep a run graph: incidents in a non-terminal stage, PENDING intents and live intent leases, and when anything was last recorded in it (stage events); now and every time on the engine clock
// returns: single-row
CALL { MATCH (i:Incident) WHERE i.stage IS NOT NULL AND NOT i.stage IN $terminal RETURN count(i) AS open }
CALL { MATCH (it:Intent {state:'PENDING'})
       RETURN count(it) AS pending,
              sum(CASE WHEN coalesce(it.lease_until, 0) >= timestamp() THEN 1 ELSE 0 END) AS leased }
CALL { MATCH (se:StageEvent) RETURN max(se.at) AS last_at }
RETURN open, pending, leased, last_at, timestamp() AS now
LIMIT 1
