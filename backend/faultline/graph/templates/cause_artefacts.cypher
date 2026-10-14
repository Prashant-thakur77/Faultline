// id: Q-CAUSE-ART
// purpose: G7 correlation: does the cause carry an artefact the code specialist can inspect (commits it CONTAINS, facts its diff ASSERTS)? Without one, the code channel's silence about it is not disagreement
// returns: single-row
// seen: id
MATCH (d:Node {id: $cause})
RETURN d.id AS id, size([(d)-[:CONTAINS]->(c:Commit) | c]) AS commits, size([(d)-[:ASSERTS]->(f:ChangeFact) | f]) AS facts
LIMIT 1
