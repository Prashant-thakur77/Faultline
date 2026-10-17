// id: Q-LEARN-GUIDE
// purpose: guidelines (M21) of one incident family in the given statuses: a trusted rejection reason proposed each one for the family and action kind; a human promotes it to active (the option then needs an explicit override) or dismisses it. With who proposed and decided it and the event it derives from
// home: oncall
// seen: id, event
MATCH (gd:Guideline)
WHERE gd.family = $family AND gd.status IN $statuses
RETURN gd.id AS id, gd.text AS text, gd.family AS family, gd.action_kind AS action_kind, gd.status AS status,
       gd.source AS source, gd.by AS by, gd.by_name AS by_name, gd.at AS at, gd.incident AS incident, gd.graph AS graph,
       gd.option AS option, gd.source_event AS event, gd.decided_by AS decided_by, gd.decided_by_name AS decided_by_name,
       gd.decided_at AS decided_at
ORDER BY at DESC, id
LIMIT 50
