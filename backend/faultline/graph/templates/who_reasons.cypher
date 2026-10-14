// id: Q-ORG-WHO
// purpose: who_fixes people and the reasons for each, computed in Cypher (M14 #6): every active recent author (commits on the component's files since $since), past resolver (an incident that affected it), on-call person of the owner team at $now and active owner-team member, with how many recent commits they made on it, which of its incidents they resolved (sorted), whether they are on call and whether they are an owner-team member; name, teams and the owner team for display. The caller only formats the reasons
// seen: person
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
  MATCH (c)<-[:PART_OF]-(:File)<-[:TOUCHES]-(cm:Commit)<-[:AUTHORED]-(p:Person)
  WHERE cm.at >= $since AND p.active
  WITH p.id AS pid, count(DISTINCT cm) AS n
  RETURN collect(pid) AS authors, collect([pid, n]) AS author_commits
}
CALL {
  WITH c
  MATCH (r:Person)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(c)
  WHERE r.active
  WITH r.id AS pid, i.id AS iid
  ORDER BY pid, iid
  WITH pid, collect(DISTINCT iid) AS iids
  RETURN collect(pid) AS resolvers, collect([pid, iids]) AS resolver_incidents
}
CALL {
  WITH owner_teams
  MATCH (o:Person)-[oc:ON_CALL]->(t:Team)
  WHERE t.id IN owner_teams AND oc.from <= $now AND $now < oc.to AND o.active
  RETURN collect(DISTINCT o.id) AS oncall
}
CALL {
  WITH owner_teams
  MATCH (m:Person)-[:MEMBER_OF]->(t:Team)
  WHERE t.id IN owner_teams AND m.active
  RETURN collect(DISTINCT m.id) AS members
}
// (the commit count and resolved incidents of each person come from the subqueries above and are looked up per person
//  below: a filtered per-person subquery at this point returned nothing on 6.0.2, the docs/upstream/17 filter placement)
UNWIND authors + resolvers + oncall + members AS pid
WITH DISTINCT owner_teams, pid, oncall, members, author_commits, resolver_incidents
MATCH (p:Person {id: pid})
RETURN p.id AS person, p.name AS name, [(p)-[:MEMBER_OF]->(tm:Team) | tm.id] AS teams, owner_teams[0] AS team,
       coalesce(head([x IN author_commits WHERE x[0] = pid | x[1]]), 0) AS commits,
       coalesce(head([x IN resolver_incidents WHERE x[0] = pid | x[1]]), []) AS resolved,
       pid IN oncall AS oncall, pid IN members AS member
ORDER BY person
LIMIT 100
