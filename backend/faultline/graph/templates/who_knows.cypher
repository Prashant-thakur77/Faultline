// id: Q-ORG-KNOWS
// purpose: who_fixes projection, built in Cypher: the KNOWS_ABOUT pairs around a component, one row per undirected pair, keyset-paged on the (a, b) tuple after ($after_a, $after_b). Pairs: person-file (an active person's commits on the component's files since $since), file-component (every file of the component), person-incident and incident-component (active people who resolved an incident that affected it), person-component (active on-call for the owner team at $now), person-person (COLLABORATES with w >= $min_collab between any two of those people or the owner team's active members). The caller writes each pair both ways into a scratch graph for algo.HarmonicCentrality (Q-ORG-HARM)
// seen: a, b
// (no top-level OPTIONAL MATCH: on 6.0.2 a CALL subquery after one misplaces its WHERE filter on a node it binds and
//  returns nothing, docs/upstream/17; the owner team is read in its own subquery instead)
MATCH (c:Node {id: $target})
CALL {
  WITH c
  MATCH (t:Team)-[:OWNS]->(c)
  RETURN collect(t.id) AS owner_teams
}
CALL {
  WITH c
  MATCH (c)<-[:PART_OF]-(f:File)<-[:TOUCHES]-(cm:Commit)<-[:AUTHORED]-(p:Person)
  WHERE cm.at >= $since AND p.active
  RETURN collect(DISTINCT [p.id, 'person', f.id, 'file']) AS authored, collect(DISTINCT p.id) AS authors
}
CALL {
  WITH c
  MATCH (f:File)-[:PART_OF]->(c)
  RETURN collect(DISTINCT [f.id, 'file', c.id, 'component']) AS files
}
CALL {
  WITH c
  MATCH (r:Person)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(c)
  WHERE r.active
  RETURN collect(DISTINCT [r.id, 'person', i.id, 'incident']) + collect(DISTINCT [i.id, 'incident', c.id, 'component']) AS resolved,
         collect(DISTINCT r.id) AS resolvers
}
CALL {
  WITH c, owner_teams
  MATCH (o:Person)-[oc:ON_CALL]->(t:Team)
  WHERE t.id IN owner_teams AND oc.from <= $now AND $now < oc.to AND o.active
  RETURN collect(DISTINCT [o.id, 'person', c.id, 'component']) AS oncall, collect(DISTINCT o.id) AS oncallers
}
CALL {
  WITH owner_teams
  MATCH (m:Person)-[:MEMBER_OF]->(t:Team)
  WHERE t.id IN owner_teams AND m.active
  RETURN collect(DISTINCT m.id) AS members
}
WITH authored + files + resolved + oncall AS pairs, authors + resolvers + oncallers + members AS people
CALL {
  WITH people
  MATCH (a:Person)-[k:COLLABORATES]->(b:Person)
  WHERE a.id IN people AND b.id IN people AND coalesce(k.w, 1.0) >= $min_collab
  RETURN collect(DISTINCT [a.id, 'person', b.id, 'person']) AS collab
}
UNWIND pairs + collab AS e
WITH DISTINCT e[0] AS a, e[1] AS a_kind, e[2] AS b, e[3] AS b_kind
WITH a, a_kind, b, b_kind
WHERE a > $after_a OR (a = $after_a AND b > $after_b)
RETURN a, a_kind, b, b_kind
ORDER BY a, b
LIMIT 100
