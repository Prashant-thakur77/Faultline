// id: Q-EDGE-PROPOSALS
// purpose: the learned-edge proposals of an incident (M15 #4): what a verified fix showed the graph was missing, with the measured share, the reason, the plan hash a human approves and the status
// seen: id, src, dst
MATCH (i:Incident {id: $inc})-[:HAS_PROPOSAL]->(p:EdgeProposal)
RETURN p.id AS id, p.src AS src, p.dst AS dst, p.cap AS cap, p.why AS why, p.status AS status, p.plan_hash AS plan_hash,
       p.action_id AS action, p.change_id AS change, p.approved_by AS approved_by
ORDER BY id
LIMIT 20
