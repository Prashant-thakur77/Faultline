// id: Q-ONCALL-STATS
// purpose: on-call numbers of one graph since $since, computed here: pages sent (page and escalation kinds) and the people they paged; per incident a PERSON acknowledged, the time from its first page to that first ack (MTTA parts; a demo run-token ack is not a responder); per resolved incident the time from opening to RESOLVED (MTTR parts); incidents RESOLVED under a standing contract (approved by contract)
// home: oncall
// returns: single-row
CALL { MATCH (pg:Page)-[:PAGES]->(p:Person) WHERE pg.sent_at >= $since AND pg.kind IN ['page', 'escalation']
       RETURN count(DISTINCT pg.id) AS pages, collect(DISTINCT p.id) AS people, count(DISTINCT pg.incident) AS incidents_paged }
CALL { MATCH (pg:Page) WHERE pg.sent_at >= $since AND pg.kind IN ['page', 'escalation']
       WITH pg.incident AS inc, min(pg.sent_at) AS first_page,
            min(CASE WHEN pg.acked_by IS NOT NULL THEN pg.acked_at END) AS first_ack
       WHERE first_ack IS NOT NULL
       RETURN count(inc) AS acked_incidents, sum(first_ack - first_page) AS ack_ms_sum, collect(first_ack - first_page) AS ack_ms }
CALL { MATCH (i:Incident)-[:HAS_RUN]->(:Run)-[:HAS_STAGE]->(se:StageEvent) WHERE i.opened_at >= $since AND se.stage = 'RESOLVED'
       WITH i, min(se.at) AS resolved_at
       RETURN count(i) AS resolved_incidents, sum(resolved_at - i.opened_at) AS resolve_ms_sum, collect(resolved_at - i.opened_at) AS resolve_ms }
CALL { MATCH (i:Incident)-[:HAS_INTENT]->(:Intent)<-[:APPROVED]-(ap:Approval)
       WHERE i.opened_at >= $since AND i.stage = 'RESOLVED' AND ap.approver_id STARTS WITH 'contract:'
       RETURN count(DISTINCT i.id) AS under_contract, collect(DISTINCT i.id) AS under_contract_ids }
RETURN pages, people, incidents_paged, acked_incidents, ack_ms_sum, ack_ms, resolved_incidents, resolve_ms_sum,
       resolve_ms, under_contract, under_contract_ids
LIMIT 1
