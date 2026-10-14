// id: Q-PRE-2
// purpose: preflight: per changed component, past incidents its changes caused, owner team, active reviewers (not the author), runbooks
// seen: changed, team, reviewers, past_incidents
MATCH (pr:PR {id:$pr})-[:TOUCHES]->(:File)-[:PART_OF]->(s)
WITH DISTINCT pr, s
RETURN s.id AS changed, [x IN labels(s) WHERE x <> 'Node'][0] AS label,
       [(s)<-[:CHANGED]-(:Deploy)-[:CAUSED]->(i:Incident) | i.id] AS past_incidents,
       [(s)<-[:OWNS]-(t:Team) | t.id] AS team,
       [(s)<-[:OWNS]-(:Team)<-[:MEMBER_OF]-(p:Person) WHERE p.active AND p.id <> pr.author_id | p.id] AS reviewers,
       [(r:Runbook)-[:RUNBOOK_FOR]->(s) WHERE r.valid_to IS NULL | r.id] AS runbooks
ORDER BY changed
LIMIT 20
