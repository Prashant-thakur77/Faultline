// id: Q-PROV-1
// purpose: "why do you believe this?": the run's own reasoning as a graph, bounded: the confirmed hypothesis and the change it BLAMES, the Evidence that SUPPORTS it, the ToolCall that PRODUCED each piece, the crew or specialist Task that MADE the call and its Agent, and the graph nodes the call SAW. Read-only, anchored on the incident
// seen: blames
MATCH (i:Incident {id: $inc})-[:HYPOTHESIZES]->(h:Hypothesis)-[:BLAMES]->(c)
WHERE h.status = 'confirmed'
MATCH (e:Evidence)-[:SUPPORTS]->(h)
OPTIONAL MATCH (tc:ToolCall)-[:PRODUCED_EVIDENCE]->(e)
OPTIONAL MATCH (t:Task)-[:MADE]->(tc)
RETURN h.id AS hypothesis, c.id AS blames, e.id AS evidence, e.tool AS tool, e.template AS template, e.summary AS summary,
       tc.id AS tool_call, tc.ms AS ms, t.id AS task, t.role AS role, t.kind AS task_kind, t.owner AS agent,
       [(tc)-[:SAW]->(n) | n.id][0..6] AS saw
ORDER BY evidence, tool_call
LIMIT 60
