// id: Q-WHATIF-2
// purpose: what-if: WCC component ids of the protected entry and the given services on the branch (same id = still connected)
// seen: id
CALL {algo:wcc}({nodeLabels: ['Service', 'Datastore', 'Table', 'KPI', 'Dashboard'], relationshipTypes: ['PROPAGATES_TO']}) YIELD node, componentId
WITH node, componentId WHERE node.id IN $ids
RETURN node.id AS id, componentId
ORDER BY id
LIMIT 100
