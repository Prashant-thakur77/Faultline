// id: Q-MEM-6
// purpose: incident families: algo.labelPropagation over incidents, their symptoms and the components their causes changed (read-only, on the tenant graph); the family holding $inc first
// seen: incidents
CALL {algo:cdlp}({nodeLabels: ['Incident', 'Symptom', 'Deploy', 'Service', 'Datastore', 'Transform', 'Table'], relationshipTypes: ['HAS_SYMPTOM', 'CAUSED', 'CHANGED'], maxIterations: 20}) YIELD node, communityId
WITH communityId, collect(CASE WHEN 'Incident' IN labels(node) THEN node.id END) AS incidents
WHERE size(incidents) >= 2
RETURN communityId, incidents, size(incidents) AS size, $inc IN incidents AS mine
ORDER BY mine DESC, size DESC, communityId
LIMIT 50
