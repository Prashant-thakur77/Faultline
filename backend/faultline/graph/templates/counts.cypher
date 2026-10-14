// id: Q-COUNT-1
// purpose: node and edge counts of a tenant graph (tenant switch, status panel)
// returns: single-row
MATCH (n:Node)
WITH count(n) AS nodes
MATCH ()-[r]->()
RETURN nodes, count(r) AS edges
LIMIT 1
