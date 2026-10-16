// id: Q-SIM-SLO
// purpose: one page of the simulated world SLO budgets (service, budget), keyset-paged by slo id: the simulator raises slo_burn alerts from them, as a monitoring system would
// seen: slo, service
// Paged because globex has 130 SLOs, more than one read under the product-wide LIMIT cap.
MATCH (o:SLO)-[:FOR]->(n:Node)
WHERE o.id > $after
RETURN o.id AS slo, n.id AS service, o.budget AS budget
ORDER BY slo
LIMIT 100
