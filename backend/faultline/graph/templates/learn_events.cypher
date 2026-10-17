// id: Q-LEARN-EVENTS
// purpose: the most recent learning events of the tenant (the learned-state panel): who did what, on which family and incident, and when
// home: oncall
// seen: id, person
MATCH (e:LearnEvent)
RETURN e.id AS id, e.kind AS kind, e.person AS person, e.person_name AS person_name, e.family AS family,
       e.action_kind AS action_kind, e.option AS option, e.at AS at, e.incident AS incident, e.graph AS graph,
       e.via AS via, e.reason AS reason, e.verdict AS verdict, e.ack_ms AS ack_ms, e.text AS text
ORDER BY at DESC, id
LIMIT 50
