// id: Q-BRAIN-SUB
// purpose: a brain answer drawn as a graph (M17): how the ids an answer cites connect, through paths of at most 2 hops in the domain graph (run bookkeeping such as ToolCall, Evidence, Run, Turn and Session is never a hop, or every cited id would connect through the question's own records)
MATCH (a:Node) WHERE a.id IN $ids
MATCH (b:Node) WHERE b.id IN $ids AND a.id < b.id
MATCH p = (a)-[*1..2]-(b)
WHERE none(n IN nodes(p) WHERE n:ToolCall OR n:Evidence OR n:Run OR n:Turn OR n:Session OR n:StageEvent OR n:Task OR n:Agent)
RETURN [n IN nodes(p) | {id: n.id, label: labels(n)[1], name: coalesce(n.name, n.title, n.id)}] AS nodes,
       [r IN relationships(p) | {rel: type(r), source: startNode(r).id, target: endNode(r).id}] AS rels,
       length(p) AS hops, a.id AS from, b.id AS to
ORDER BY hops, from, to
LIMIT 60
