// id: Q-NOTE-REFUSED
// purpose: why W-NOTE-1 wrote nothing, read-only on agentmem_<tenant>: which `about` ids are not nodes of the graph, whether the reply target exists, and how many notes the author wrote in the last 24 h (engine clock) against its quota
// home: agentmem
// returns: single-row
CALL {
  UNWIND $about AS i
  OPTIONAL MATCH (x:Node {id: i})
  WITH i, x WHERE x IS NULL
  RETURN collect(i) AS unknown_about
}
CALL {
  MATCH (p:Note) WHERE p.id = $reply_to AND (coalesce(p.visibility, 'shared') = 'shared' OR p.agent = $principal)
  RETURN count(p) AS replies_found
}
CALL {
  MATCH (a:Author {id: $principal})-[:WROTE]->(r:Note) WHERE r.created_at >= timestamp() - 86400000
  RETURN count(r) AS used
}
RETURN unknown_about, $reply_to = '' OR replies_found > 0 AS reply_ok, used
LIMIT 1
