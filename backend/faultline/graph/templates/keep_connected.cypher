// id: Q-KEEP-1
// purpose: what-if: revenue-path services that must STAY connected after a containment cut (all revenue-path services except the failing one and the protected ones)
// seen: id
MATCH (s:Service)
WHERE s.revenue_path = true AND NOT s.id IN $exclude
RETURN s.id AS id, s.tier AS tier
ORDER BY tier, id
LIMIT 10
