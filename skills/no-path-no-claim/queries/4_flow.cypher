// G5, sufficiency: the most error share the changed component can push into the symptom over failure edges, bounded
// by each edge's capacity. Below 0.8 x the observed share, the change cannot explain the impact on its own.
// Params: $component, $symptom.
MATCH (s:Node {id: $component}), (t:Node {id: $symptom})
CALL algo.maxFlow({sourceNodes: [s], targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow
RETURN maxFlow AS max_flow
LIMIT 1
