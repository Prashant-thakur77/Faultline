// id: Q-CUT-1
// purpose: containment: max-flow from the failing component to the protected set over cut_cost (edges + edgeFlows; cut computed in code)
// returns: single-row
// seen: flow_edges
MATCH (f:Node {id:$failing})
MATCH (p:Node) WHERE p.id IN $protect
WITH f, collect(p) AS prot
WHERE size(prot) > 0
CALL {algo:maxflow}({sourceNodes: [f], targetNodes: prot, relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cut_cost'}) YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | [startNode(e).id, endNode(e).id]] AS flow_edges, edgeFlows AS flows, maxFlow AS max_flow
LIMIT 1
