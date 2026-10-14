// id: Q-SIM-SLO
// purpose: the simulated world's SLO budgets (service, budget): the simulator raises slo_burn alerts from them, as a monitoring system would
// seen: slo, service
MATCH (o:SLO)-[:FOR]->(n:Node)
RETURN o.id AS slo, n.id AS service, o.budget AS budget
ORDER BY slo
LIMIT 100
