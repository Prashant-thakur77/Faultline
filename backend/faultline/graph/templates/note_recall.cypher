// id: Q-NOTE-RECALL
// purpose: shared agent notes (T2), recalled in ONE query on agentmem_<tenant> by meaning (vecf32 index over the note text, cosine ≥ $floor) and by graph distance (notes about $focus or a component within $hops PROPAGATES_TO hops either way), unexpired on the engine clock, ranked inside the engine by faultline.noteScore ($w = weights.yaml notes), with each note's components and its replies; no `seen` column: a note is a lead, never evidence for the gate (G1)
// home: agentmem
// (an empty $focus or a null $q switches a route off; the empty UNWIND keeps the procedure from running at all)
CALL {
  UNWIND CASE WHEN $focus = '' THEN [] ELSE [1] END AS one
  MATCH p = (f:Node {id: $focus})-[:PROPAGATES_TO*0..3]-(x:Node)
  WHERE length(p) <= $hops
  WITH x, min(length(p)) AS h
  MATCH (n:Note)-[:ABOUT]->(x)
  RETURN n, h AS hops, null AS sim
  UNION ALL
  UNWIND CASE WHEN $q IS NULL THEN [] ELSE [1] END AS one
  CALL db.idx.vector.queryNodes('Note', 'embedding', 20, vecf32($q)) YIELD node, score
  WITH node, 1.0 - score AS sim WHERE sim >= $floor
  RETURN node AS n, null AS hops, sim
}
WITH n, min(hops) AS hops, max(sim) AS sim
WHERE n.expires_at > timestamp()
WITH n, hops, sim, faultline.noteScore($w, sim, hops, (timestamp() - n.created_at) / 60000.0) AS score
RETURN n.id AS id, n.agent AS agent, n.name AS name, n.kind AS kind, n.text AS text, n.created_at AS created_at,
       n.expires_at AS expires_at, [(n)-[:ABOUT]->(c) | c.id] AS about, hops, faultline.round4(sim) AS similarity,
       [(r:Note)-[rt:REPLY_TO]->(n) | {id: r.id, agent: r.agent, stance: rt.stance, text: r.text}] AS replies,
       faultline.round4(score) AS score
ORDER BY score DESC, id
LIMIT 20
