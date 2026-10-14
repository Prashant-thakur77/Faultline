// id: Q-CONN-2
// purpose: containment precondition (algo.WCC): is the failing component in the same connected component as anything protected? (no → nothing to cut)
// returns: single-row
// seen: protected_in_component
CALL {algo:wcc}({nodeLabels: ['Service', 'Datastore', 'Table', 'KPI', 'Dashboard'], relationshipTypes: ['PROPAGATES_TO']}) YIELD node, componentId
WITH componentId, collect(node.id) AS members
WHERE $target IN members
RETURN componentId, [p IN $protect WHERE p IN members] AS protected_in_component, size(members) AS size
ORDER BY componentId
LIMIT 1
