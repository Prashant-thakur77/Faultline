/**
 * The Cypher shown on the home page's proof story: verbatim lines from backend/faultline/graph/templates,
 * with each `{algo:x}` placeholder written as the procedure the smoke suite resolved on the pinned engine
 * (backend/faultline/graph/algo/registry.py). proofSnippets.test.ts fails if a line drifts from its template.
 */
export const ALGO_NAMES: Record<string, string> = { wcc: "algo.WCC", sppaths: "algo.SPpaths", maxflow: "algo.maxFlow" };

export type Snippet = { id: string; file: string; code: string };

export const SNIPPETS: Record<string, Snippet> = {
  storm: {
    id: "Q-STORM-WCC",
    file: "storm_wcc.cypher",
    code: `CALL algo.WCC({nodeLabels: ['Node'], relationshipTypes: ['PROPAGATES_TO']}) YIELD node, componentId
WITH node, componentId WHERE size(coalesce(node.alerts, [])) > 0`,
  },
  path: {
    id: "Q-GATE-1",
    file: "gate_path.cypher",
    code: `MATCH (c:Node {id:$cause}), (s:Node {id:$symptom})
CALL algo.SPpaths({sourceNode: c, targetNode: s, relTypes: ['CHANGED', 'GATES', 'PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 3}) YIELD path, pathWeight`,
  },
  flow: {
    id: "Q-GATE-3",
    file: "gate_flow.cypher",
    code: `MATCH (t:Node {id:$symptom})
CALL algo.maxFlow({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow
RETURN maxFlow AS max_flow, size(srcs) AS sources`,
  },
  proof: {
    id: "Q-GATE-1",
    file: "gate_path.cypher",
    code: `RETURN [n IN nodes(path) | n.id] AS chain, [r IN relationships(path) | type(r)] AS rels, pathWeight AS weight, length(path) AS hops,
[r IN relationships(path) | coalesce(r.from_incident, '')] AS learned_from`,
  },
  cut: {
    id: "Q-CUT-1",
    file: "cut_flow.cypher",
    code: `CALL algo.maxFlow({sourceNodes: [f], targetNodes: prot, relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cut_cost'}) YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | [startNode(e).id, endNode(e).id]] AS flow_edges, edgeFlows AS flows, maxFlow AS max_flow`,
  },
  writeback: {
    id: "Q-WB-1",
    file: "writeback_check.cypher",
    code: `MATCH (inc:Incident {id:$inc})
OPTIONAL MATCH (c:Node {id:$cause})-[:CAUSED]->(inc)
OPTIONAL MATCH (inc)-[:RESOLVED_BY]->(a:Action {id:$aid})`,
  },
};

/** The "plug it into your agent" tabs: the repo's own MCP entry, a REST call and a gate query (checked in the test). */
export const API_TABS: { id: string; label: string; meta: string; lang: "json" | "shell" | "cypher"; code: string }[] = [
  {
    id: "mcp", label: "MCP", meta: ".mcp.json", lang: "json",
    code: `{
  "mcpServers": {
    "faultline": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "faultline.mcp_server.server", "--stdio"],
      "env": { "PYTHONPATH": "backend", "FAULTLINE_TENANT": "acme" }
    }
  }
}`,
  },
  {
    id: "rest", label: "REST", meta: "POST /api/context_pack", lang: "shell",
    code: `curl -s -X POST "localhost:8400/api/context_pack?tenant=acme" \\
  -H 'content-type: application/json' \\
  -d '{"text": "checkout errors are spiking", "targets": ["checkout"], "budget_tokens": 500}'`,
  },
  { id: "cypher", label: "Cypher", meta: `${SNIPPETS.path.id} · templates/${SNIPPETS.path.file}`, lang: "cypher", code: SNIPPETS.path.code },
];
