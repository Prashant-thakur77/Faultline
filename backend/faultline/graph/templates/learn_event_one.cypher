// id: Q-LEARN-EV1
// purpose: one learning event by id (a verified fix is learned only when its approval was learned, i.e. trusted)
// home: oncall
// returns: single-row
// seen: id
MATCH (e:LearnEvent {id: $id})
RETURN e.id AS id, e.kind AS kind, e.person AS person, e.family AS family, e.action_kind AS action_kind, e.at AS at,
       e.incident AS incident, e.graph AS graph, e.via AS via
LIMIT 1
