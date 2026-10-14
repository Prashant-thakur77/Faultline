// id: Q-TIMELINE-1
// purpose: one component's history in time order: deploys that changed it, incidents that touched it (and in what role), alerts on it, ownership changes, decisions that constrain it, runbook reviews
// seen: ref
// (one comprehension per WITH: a comprehension naming a relationship variable empties later ones; docs/upstream/09)
MATCH (n:Node {id: $id})
WITH n, [(d:Deploy)-[c:CHANGED]->(n) | {at: c.at, kind: 'deploy', ref: d.id, detail: coalesce(d.kind, 'deploy') + coalesce(' ' + d.pr_id, '') + coalesce(' by ' + d.actor_id, '')}] AS deploys
WITH n, deploys, [(i:Incident)-[a:AFFECTED]->(n) | {at: i.opened_at, kind: 'incident', ref: i.id, detail: a.role + ': ' + coalesce(i.title, '')}] AS incidents
WITH n, deploys, incidents, [(t:Team)-[o:OWNED_AT]->(n) | {at: o.from, kind: 'owner', ref: t.id, detail: 'became the owning team'}] AS owners
WITH n, deploys + incidents + owners
        + [(al:Alert)-[:FIRED_ON]->(n) | {at: al.fired_at, kind: 'alert', ref: al.id, detail: coalesce(al.metric, '')}]
        + [(dc:Decision)-[:CONSTRAINS]->(n) | {at: dc.decided_at, kind: 'decision', ref: dc.id, detail: coalesce(dc.status, '') + ': ' + coalesce(dc.title, '')}]
        + [(r:Runbook)-[:RUNBOOK_FOR]->(n) WHERE r.reviewed_at IS NOT NULL | {at: r.reviewed_at, kind: 'runbook', ref: r.id, detail: 'reviewed: ' + coalesce(r.title, '')}] AS events
UNWIND events AS e
WITH e WHERE e.at >= $since AND e.at <= $until
RETURN e.at AS at, e.kind AS kind, e.ref AS ref, e.detail AS detail
ORDER BY at DESC, kind, ref
LIMIT 100
