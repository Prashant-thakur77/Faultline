// id: Q-CREW-1
// purpose: a run's crew: every step and specialist work item with its agent, timing, hand-off, contract outcome, the suspects it names, the evidence it cites and the graph calls it made (anchored pattern comprehensions: an OPTIONAL MATCH after an aggregation is an engine bug on 6.0.2)
MATCH (run:Run {id: $run})-[:HAS_TASK]->(t:Task)
RETURN t.id AS task, t.kind AS kind, t.role AS role, t.stage AS stage, t.owner AS agent, t.state AS state,
       t.status AS status, t.claimed_at AS claimed_at, t.done_at AS done_at, t.summary AS summary,
       [(p:Task)-[:NEXT]->(t) | p.id] AS after,
       [(t)-[:NAMES]->(n) | n.id] AS names,
       size([(t)-[:CITES]->(e:Evidence) | e.id]) AS cites,
       [(t)-[:MADE]->(tc:ToolCall) | {id: tc.id, tool: tc.tool, template: tc.template, ms: tc.ms, rows: tc.rows, at: tc.at}] AS calls,
       t.unknowns AS unknowns, t.limits AS limits, coalesce(t.reaps, 0) AS reaps
ORDER BY t.claimed_at, t.id
LIMIT 60
