// id: Q-CUT-3
// purpose: containment in ONE read-only query: algo.maxFlow from $failing to the protected set over cut_cost, then the min-cut inside the engine. Residual reachability from $failing runs over every PROPAGATES_TO edge of the region algo.SSpaths reaches (forward while cut_cost − flow > 1e-9, backward while flow > 1e-9), iterated to a fixpoint as a list reduction; the cut is the edges leaving that source side. The code only checks that the cut capacity equals maxFlow and that no protected node is on the source side.
// returns: single-row
// seen: flow_edges
MATCH (f:Node {id:$failing})
MATCH (p:Node) WHERE p.id IN $protect
WITH f, collect(p.id) AS prot
WHERE size(prot) > 0
CALL {
  WITH f
  CALL {algo:sspaths}({sourceNode: f, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1000}) YIELD path
  WITH f, collect(DISTINCT last(nodes(path))) + [f] AS region
  UNWIND region AS a
  MATCH (a)-[r:PROPAGATES_TO]->(b)
  WHERE b IN region
  WITH a, r, b ORDER BY a.id, b.id
  RETURN collect({rid: id(r), u: a.id, v: b.id, cost: coalesce(r.cut_cost, 0), domain: r.domain}) AS cand
}
MATCH (t:Node) WHERE t.id IN prot
WITH f, prot, cand, collect(t) AS targets
CALL {algo:maxflow}({sourceNodes: [f], targetNodes: targets, relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cut_cost'}) YIELD edges, edgeFlows, maxFlow
WITH f, prot, cand, maxFlow,
     [i IN range(0, size(edges) - 1) | {rid: id(edges[i]), u: startNode(edges[i]).id, v: endNode(edges[i]).id, flow: edgeFlows[i]}] AS fe
WITH f, prot, cand, maxFlow, fe,
     [c IN cand | {u: c.u, v: c.v, cost: c.cost, domain: c.domain,
                   flow: coalesce(head([x IN fe WHERE x.rid = c.rid | x.flow]), 0)}] AS arcs
WITH f, prot, cand, maxFlow, fe, arcs,
     [a IN arcs WHERE a.cost - a.flow > 1e-9 | [a.u, a.v]] + [a IN arcs WHERE a.flow > 1e-9 | [a.v, a.u]] AS residual
WITH f, prot, cand, maxFlow, fe, arcs,
     reduce(s = [f.id], i IN range(0, size(arcs)) | s + reduce(add = [], x IN residual |
            CASE WHEN x[0] IN s AND NOT x[1] IN s AND NOT x[1] IN add THEN add + [x[1]] ELSE add END)) AS reach
WITH f, prot, cand, maxFlow, fe, arcs, CASE WHEN maxFlow <= 1e-9 THEN [f.id] ELSE reach END AS side
WITH prot, cand, maxFlow, fe, side,
     [a IN arcs WHERE maxFlow > 1e-9 AND a.u IN side AND NOT a.v IN side AND a.cost > 1e-9 |
      {u: a.u, v: a.v, cut_cost: a.cost, domain: a.domain}] AS cut
RETURN cut, reduce(total = 0, c IN cut | total + c.cut_cost) AS cut_total, maxFlow AS max_flow, side AS source_side,
       [x IN prot WHERE x IN side] AS protected_on_source_side, size(cand) AS candidates,
       [e IN fe | [e.u, e.v]] AS flow_edges
LIMIT 1
