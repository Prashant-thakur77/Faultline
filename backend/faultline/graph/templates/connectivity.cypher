// id: Q-CONN-1
// purpose: connectivity (WCC) of the failure-flow graph: is the protected entry still connected?
// seen: members
CALL {algo:wcc}({nodeLabels: ['Service', 'Datastore', 'Table', 'KPI', 'Dashboard'], relationshipTypes: ['PROPAGATES_TO']}) YIELD node, componentId
RETURN componentId, collect(node.id) AS members, count(node) AS size
ORDER BY size DESC, componentId
LIMIT 50
