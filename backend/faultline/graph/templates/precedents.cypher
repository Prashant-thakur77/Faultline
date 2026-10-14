// id: Q-MEM-2
// purpose: precedents: incidents this one RECALLED whose own cause changed the same component as the confirmed cause (feeds PRECEDENT_FOR at write-back)
// seen: id
MATCH (cur:Incident {id:$inc})-[r:RECALLED]->(p:Incident)
MATCH (t:Node {id:$target})<-[:CHANGED]-(:Deploy)-[:CAUSED]->(p)
RETURN DISTINCT p.id AS id, r.similarity AS similarity
ORDER BY similarity DESC, id
LIMIT 10
