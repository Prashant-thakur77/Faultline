#!/usr/bin/env node
/**
 * faultline-mcp: Faultline's read-only FalkorDB graph tools for any MCP client that speaks stdio (Claude Desktop,
 * Cursor, Claude Code, Windsurf, ...). It runs a local stdio MCP server and forwards every request to a Faultline
 * MCP endpoint over Streamable HTTP: by default the public demo (synthetic data, a public read-only key), or your own
 * deployment with --url and --key. Nothing is cached or rewritten: tools, resources and prompts are the server's.
 *
 *   npx -y @prashantthakur77/faultline-mcp                       # the public demo
 *   npx -y @prashantthakur77/faultline-mcp --url https://host/mcp --key <bearer key>
 *   FAULTLINE_MCP_URL=... FAULTLINE_MCP_KEY=... npx -y @prashantthakur77/faultline-mcp
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  GetPromptRequestSchema,
  ListPromptsRequestSchema,
  ListResourcesRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const DEMO_URL = "https://13-203-185-119.sslip.io/mcp";
// Public on purpose: bound to the synthetic `acme` tenant, read-only (GRAPH.RO_QUERY), rate-limited per key.
const DEMO_KEY = "fl_demo_f5be019593a8c0424d247a5d";

const pkg = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "package.json"), "utf8"));

function parseArgs(argv) {
  const out = { url: process.env.FAULTLINE_MCP_URL || "", key: process.env.FAULTLINE_MCP_KEY || "" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--help" || a === "-h") out.help = true;
    else if (a === "--version" || a === "-v") out.version = true;
    else if (a === "--url") out.url = argv[++i] || "";
    else if (a.startsWith("--url=")) out.url = a.slice(6);
    else if (a === "--key") out.key = argv[++i] || "";
    else if (a.startsWith("--key=")) out.key = a.slice(6);
    else throw new Error(`unknown argument ${a} (try --help)`);
  }
  if (!out.url) {
    out.url = DEMO_URL;
    if (!out.key) out.key = DEMO_KEY;
  }
  return out;
}

const HELP = `faultline-mcp ${pkg.version}: Faultline's read-only FalkorDB graph tools over MCP (stdio).

Usage:
  npx -y @prashantthakur77/faultline-mcp [--url <https://host/mcp>] [--key <bearer key>]

With no --url it connects to the public demo (${DEMO_URL}, synthetic data, a public read-only key).
Environment: FAULTLINE_MCP_URL, FAULTLINE_MCP_KEY.
Every tool answers from a read-only FalkorDB query and returns the Cypher it ran, its parameters and timing.
Docs: https://github.com/Prashant-thakur77/Faultline/blob/main/docs/MCP.md`;

function log(msg) {
  process.stderr.write(`[faultline-mcp] ${msg}\n`);   // stdout is the MCP channel; logs go to stderr
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (e) {
    log(e.message);
    process.exit(2);
  }
  if (opts.help) {
    process.stdout.write(HELP + "\n");
    return;
  }
  if (opts.version) {
    process.stdout.write(pkg.version + "\n");
    return;
  }

  const headers = opts.key ? { Authorization: `Bearer ${opts.key}` } : {};
  const remote = new Client({ name: "faultline-mcp", version: pkg.version });
  try {
    await remote.connect(new StreamableHTTPClientTransport(new URL(opts.url), { requestInit: { headers } }));
  } catch (e) {
    log(`cannot reach ${opts.url}: ${e?.message || e}`);
    log("check the URL and the bearer key (a 401 means the key was refused)");
    process.exit(1);
  }
  const caps = remote.getServerCapabilities() || {};
  const info = remote.getServerVersion() || {};
  log(`connected to ${opts.url} (${info.name || "faultline"} ${info.version || ""})`.trim());

  const server = new Server(
    { name: "faultline", version: pkg.version },
    { capabilities: { tools: caps.tools ? {} : undefined, resources: caps.resources ? {} : undefined,
                      prompts: caps.prompts ? {} : undefined }, instructions: remote.getInstructions?.() },
  );
  if (caps.tools) {
    server.setRequestHandler(ListToolsRequestSchema, (req) => remote.listTools(req.params));
    server.setRequestHandler(CallToolRequestSchema, (req) => remote.callTool(req.params));
  }
  if (caps.resources) {
    server.setRequestHandler(ListResourcesRequestSchema, (req) => remote.listResources(req.params));
    server.setRequestHandler(ListResourceTemplatesRequestSchema, (req) => remote.listResourceTemplates(req.params));
    server.setRequestHandler(ReadResourceRequestSchema, (req) => remote.readResource(req.params));
  }
  if (caps.prompts) {
    server.setRequestHandler(ListPromptsRequestSchema, (req) => remote.listPrompts(req.params));
    server.setRequestHandler(GetPromptRequestSchema, (req) => remote.getPrompt(req.params));
  }
  const shutdown = async () => {
    await Promise.allSettled([server.close(), remote.close()]);
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  await server.connect(new StdioServerTransport());
}

main().catch((e) => {
  log(e?.stack || String(e));
  process.exit(1);
});
