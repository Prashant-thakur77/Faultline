// id: Q-KGAP-1
// purpose: knowledge gaps (M21): company-brain questions trusted users asked that the graph could not answer (refused or nothing documented), how often and when, in the given statuses; the teams that own what each question was about are who should document it
// home: oncall
// seen: id, about, owners
MATCH (k:KnowledgeGap)
WHERE k.status IN $statuses
RETURN k.id AS id, k.text AS text, k.n AS n, k.first_at AS first_at, k.last_at AS last_at, k.status AS status,
       k.intent AS intent, k.reason AS reason, k.about AS about,
       [(k)-[:ABOUT]->(x:Node)<-[:OWNS]-(t:Team) | t.id] AS owners, k.events AS events
ORDER BY n DESC, last_at DESC, id
LIMIT 50
