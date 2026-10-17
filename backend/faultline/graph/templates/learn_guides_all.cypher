// id: Q-LEARN-GUIDES
// purpose: every guideline of the tenant in the given statuses (the learned-state panel), newest first, with its provenance (the rejection event, who proposed it, who promoted or dismissed it)
// home: oncall
// seen: id, event, family
MATCH (gd:Guideline)
WHERE gd.status IN $statuses
RETURN gd.id AS id, gd.text AS text, gd.family AS family, gd.action_kind AS action_kind, gd.status AS status,
       gd.source AS source, gd.by AS by, gd.by_name AS by_name, gd.at AS at, gd.incident AS incident, gd.graph AS graph,
       gd.option AS option, gd.source_event AS event, gd.decided_by AS decided_by, gd.decided_by_name AS decided_by_name,
       gd.decided_at AS decided_at
ORDER BY at DESC, id
LIMIT 100
