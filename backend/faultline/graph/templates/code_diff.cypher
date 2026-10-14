// id: Q-CODE-1
// purpose: code specialist (diff_summary): what the graph knows about one change's code. The component it CHANGED; the commits it CONTAINS, the files they TOUCH and the component each file is PART_OF; the PRs that contain those commits; the commit authors; the typed facts its diff ASSERTS. code_on_target / facts_on_target say whether that code lands on the CHANGED component. There is no function-level code graph: a file path is the finest grain
// returns: single-row
// seen: id, target, commits, files, prs, authors
MATCH (d:Deploy {id:$id})
OPTIONAL MATCH (d)-[:CHANGED]->(t:Node)
RETURN d.id AS id, d.kind AS kind, d.at AS at, d.sha AS sha, t.id AS target,
       [(d)-[:CONTAINS]->(c:Commit) | c.id] AS commits,
       [(d)-[:CONTAINS]->(:Commit)-[:TOUCHES]->(f:File) | f.id] AS files,
       [(d)-[:CONTAINS]->(:Commit)-[:TOUCHES]->(:File)-[:PART_OF]->(x:Node) | x.id] AS file_components,
       [(d)-[:CONTAINS]->(:Commit)<-[:CONTAINS]-(p:PR) | p.id] AS prs,
       [(d)-[:CONTAINS]->(:Commit)<-[:AUTHORED]-(a:Person) | a.id] AS authors,
       [(d)-[:ASSERTS]->(cf:ChangeFact) | [cf.key, cf.file_id]] AS facts,
       size([(d)-[:CONTAINS]->(:Commit)-[:TOUCHES]->(:File)-[:PART_OF]->(t) | 1]) > 0 AS code_on_target,
       size([(d)-[:ASSERTS]->(:ChangeFact)-[:ABOUT]->(t) | 1]) > 0 AS facts_on_target
LIMIT 1
