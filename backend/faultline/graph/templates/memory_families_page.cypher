// id: Q-MEM-6P
// purpose: incident families, paged for seed-time consolidation over a whole history (Q-MEM-6 reads the 50 largest; a 10k-service tenant has more): the same algo.labelPropagation projection, keyset-paged by communityId > $after in communityId order. The caller reads every page before it writes anything, so the projection cannot change between pages
// seen: incidents
CALL {algo:cdlp}({nodeLabels: ['Incident', 'Symptom', 'Deploy', 'Service', 'Datastore', 'Transform', 'Table'], relationshipTypes: ['HAS_SYMPTOM', 'CAUSED', 'CHANGED'], maxIterations: 20}) YIELD node, communityId
WITH communityId, collect(CASE WHEN 'Incident' IN labels(node) THEN node.id END) AS incidents
WITH communityId, incidents
WHERE size(incidents) >= 2 AND communityId > $after
RETURN communityId, incidents, size(incidents) AS size
ORDER BY communityId
LIMIT 100
