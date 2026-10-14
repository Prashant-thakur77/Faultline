// id: Q-STORM-WCC
// purpose: alert-storm grouping (runs on the scratch projection of Q-STORM-EDGES): algo.WCC over the alerting targets and the failure-carrying PROPAGATES_TO edges; every component that holds an alert is ONE incident group
// seen: alerts, targets
CALL {algo:wcc}({nodeLabels: ['Node'], relationshipTypes: ['PROPAGATES_TO']}) YIELD node, componentId
WITH node, componentId WHERE size(coalesce(node.alerts, [])) > 0
UNWIND node.alerts AS alert
WITH componentId, node.id AS target, node.first_at AS first_at, alert
ORDER BY alert
WITH componentId, collect(alert) AS alerts, collect(DISTINCT target) AS targets, min(first_at) AS first_at
RETURN alerts, targets, first_at, size(alerts) AS size
ORDER BY first_at, alerts[0]
LIMIT 50
