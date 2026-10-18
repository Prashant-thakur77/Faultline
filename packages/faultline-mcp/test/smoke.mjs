// Smoke test: start the bridge over stdio, as an MCP client would, and call one tool through it against the
// endpoint in FAULTLINE_MCP_URL (default: the public demo). Exits non-zero on any failure.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const bin = join(dirname(fileURLToPath(import.meta.url)), "..", "bin", "faultline-mcp.js");
const client = new Client({ name: "faultline-mcp-smoke", version: "0" });
let code = 0;
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [bin], env: { ...process.env } }));
  const { tools } = await client.listTools();
  const names = tools.map((t) => t.name);
  for (const need of ["causal_paths", "impact_bound"]) {
    if (!names.includes(need)) throw new Error(`tool ${need} missing (got ${names.length} tools)`);
  }
  const res = await client.callTool({ name: "causal_paths", arguments: { from_id: "recommendation", to_id: "checkout" } });
  const text = (res.content || []).map((c) => c.text || "").join("\n");
  if (res.isError) throw new Error(`causal_paths failed: ${text.slice(0, 300)}`);
  if (!/cypher/i.test(text)) throw new Error(`causal_paths answered without its Cypher: ${text.slice(0, 300)}`);
  console.log(`ok: ${tools.length} tools; causal_paths(recommendation → checkout) answered with its Cypher`);
} catch (e) {
  console.error(`smoke FAILED: ${e?.message || e}`);
  code = 1;
} finally {
  await client.close().catch(() => {});
}
process.exit(code);
