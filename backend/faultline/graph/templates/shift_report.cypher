// id: Q-SHIFT-REPORT
// purpose: the shift report of one graph for the window $from to $to: incidents opened, pages sent, acks, approved actions with their verdicts, standing-contract uses and hand-offs, each newest first and capped at 50
// home: oncall
// returns: single-row
CALL { MATCH (i:Incident) WHERE i.opened_at >= $from AND i.opened_at < $to
       WITH i ORDER BY i.opened_at DESC LIMIT 50
       RETURN collect({id: i.id, title: i.title, stage: i.stage, opened_at: i.opened_at, onset_at: i.onset_at}) AS incidents }
CALL { MATCH (pg:Page)-[:PAGES]->(p:Person) WHERE pg.sent_at >= $from AND pg.sent_at < $to
       WITH pg, p ORDER BY pg.sent_at DESC LIMIT 50
       RETURN collect({id: pg.id, incident: pg.incident, kind: pg.kind, urgency: pg.urgency, status: pg.status,
                       sent_at: pg.sent_at, attempt: pg.attempt, person: p.id, name: p.name}) AS pages }
CALL { MATCH (a:Person)-[k:ACKED]->(pg:Page) WHERE k.at >= $from AND k.at < $to
       WITH a, k, pg ORDER BY k.at DESC LIMIT 50
       RETURN collect({id: pg.id, page: pg.id, incident: pg.incident, by: a.id, name: a.name, at: k.at, via: k.via,
                       sent_at: pg.sent_at}) AS acks }
CALL { MATCH (i:Incident)-[:HAS_INTENT]->(:Intent)<-[:APPROVED]-(ap:Approval) WHERE ap.at >= $from AND ap.at < $to
       MATCH (i)-[:HAS_PLAN]->(x:Action) WHERE x.approval_id = ap.id
       WITH i, ap, x ORDER BY ap.at DESC LIMIT 50
       RETURN collect({id: x.id, action: x.id, incident: i.id, kind: x.kind, option: x.option, approver: ap.approver_id,
                       at: ap.at, verdict: x.verdict, external_ref: x.external_ref}) AS actions }
CALL { MATCH (c:Contract)-[:USED_IN]->(u:ContractUse) WHERE u.at >= $from AND u.at < $to
       WITH c, u ORDER BY u.at DESC LIMIT 50
       RETURN collect({id: u.id, contract: c.id, incident: u.incident, action: u.action, at: u.at, verdict: u.verdict,
                       family: c.family}) AS contract_uses }
CALL { MATCH (h:Handoff)-[:TO]->(t:Person) WHERE h.at >= $from AND h.at < $to
       WITH h, t ORDER BY h.at DESC LIMIT 50
       RETURN collect({id: h.id, at: h.at, note: h.note, to: t.id, to_name: t.name, from: h.from_person,
                       from_shift: h.from_shift, incident: h.incident}) AS handoffs }
RETURN incidents, pages, acks, actions, contract_uses, handoffs
LIMIT 1
