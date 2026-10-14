// id: Q-ORG-MSF
// purpose: escalation tree: algo.MSF (maximize w) over the responders and their managers, on a scratch projection; one row per tree edge, strongest tie first (the order is the escalation order, computed here)
// seen: from, to
CALL {algo:msf}({nodeLabels: ['Node'], relationshipTypes: ['COLLABORATES'], objective: 'maximize', weightAttribute: 'w'}) YIELD edges
UNWIND edges AS e
RETURN startNode(e).id AS from, endNode(e).id AS to, e.w AS w
ORDER BY w DESC, from, to
LIMIT 100
