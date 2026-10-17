// id: Q-PAGE-NEXT
// purpose: who to page next when an incident goes unacknowledged: the first ACTIVE person in its recorded escalation order (ESCALATES_TO rank, from the algo.MSF escalation tree) who has not been paged for it yet
// home: oncall
// seen: person
MATCH (i:Incident {id:$inc})-[e:ESCALATES_TO]->(p:Person)
WHERE p.active
WITH e, p, [(p)<-[:PAGES]-(pg:Page) WHERE pg.incident = $inc | pg.id] AS paged
WHERE size(paged) = 0
RETURN p.id AS person, p.name AS name, e.rank AS rank, e.w AS w, e.via AS via
ORDER BY rank, person
LIMIT 1
