// id: Q-WB-1
// purpose: write-back re-read (second, separate RO connection): which of the written ids and edges exist
// returns: single-row
// (anchored OPTIONAL MATCH chain: an unanchored pattern comprehension returns [] on FalkorDB 6.0.2, docs/upstream/10)
MATCH (inc:Incident {id:$inc})
OPTIONAL MATCH (c:Node {id:$cause})-[:CAUSED]->(inc)
OPTIONAL MATCH (inc)-[:RESOLVED_BY]->(a:Action {id:$aid})
OPTIONAL MATCH (it:Intent)-[:EXECUTED]->(a)
OPTIONAL MATCH (ap:Approval)-[:APPROVED]->(it)
OPTIONAL MATCH (pm:Postmortem {id:$pmid})-[:DOCUMENTS]->(inc)
OPTIONAL MATCH (d:Decision {id:$did})-[:CITES]->(pm)
RETURN inc.stage AS stage, c.id AS caused, a.verdict AS verdict, it.state AS intent_state, ap.id AS approval,
       pm.id AS postmortem, d.id AS decision
LIMIT 1
