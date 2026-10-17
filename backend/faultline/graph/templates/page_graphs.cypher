// id: Q-PAGE-GRAPHS
// purpose: the durable index of graphs that hold pages (PageGraph nodes in the on-call graph), keyset-paged by graph name after $after, so escalation and the pager never depend on a capped run list; internal
// home: oncall
// internal: true
MATCH (x:PageGraph)
WHERE x.id > $after
RETURN x.id AS graph, x.last_at AS last_at
ORDER BY graph
LIMIT 100
