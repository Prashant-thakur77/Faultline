// id: Q-LEARN-GUIDE-1
// purpose: one guideline by id (promote and dismiss read it before and after the write)
// home: oncall
// returns: single-row
// seen: id, event
MATCH (gd:Guideline {id: $id})
RETURN gd.id AS id, gd.text AS text, gd.family AS family, gd.action_kind AS action_kind, gd.status AS status,
       gd.source AS source, gd.by AS by, gd.by_name AS by_name, gd.at AS at, gd.incident AS incident, gd.graph AS graph,
       gd.option AS option, gd.source_event AS event, gd.decided_by AS decided_by, gd.decided_by_name AS decided_by_name,
       gd.decided_at AS decided_at
LIMIT 1
