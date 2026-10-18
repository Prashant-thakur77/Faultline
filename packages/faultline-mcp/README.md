# @prashantthakur77/faultline-mcp

**Faultline's read-only FalkorDB graph tools for any MCP client.** Ask your agent what broke, why, what to contain and who should fix it, and get answers that come from graph queries: every result carries the Cypher it ran, its parameters and timing.

Faultline is an on-call agent built on a FalkorDB operational context graph with one rule, *no path, no claim*: a change is blamed only when FalkorDB returns a causal path from it to the symptom and shows it can carry the observed impact. This package lets your own agent use the same tools. [Project and results](https://github.com/Prashant-thakur77/Faultline) · [live demo](https://13-203-185-119.sslip.io)

## Quick start

No install needed (Node 18+). With no options it connects to the public demo: synthetic data, a public read-only key.

**Claude Code**

```bash
claude mcp add faultline -- npx -y @prashantthakur77/faultline-mcp
```

**Claude Desktop** (`claude_desktop_config.json`) or **Cursor** (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "faultline": { "command": "npx", "args": ["-y", "@prashantthakur77/faultline-mcp"] }
  }
}
```

Then ask, for example:

- *"Use causal_paths from payment to checkout, then from recommendation to checkout."* The first returns the path; the second returns none, so nothing can be blamed through it.
- *"Can D-email-88 carry checkout's impact? Use impact_bound with an observed share of 0.30."*
- *"What breaks if checkout goes down?"* (`blast_radius`)
- *"Who decided the payment timeout, and are they still here?"* (the company brain)

## Your own deployment

Point it at your Faultline server's MCP endpoint with a bearer key bound to your tenant:

```bash
npx -y @prashantthakur77/faultline-mcp --url https://faultline.example.com/mcp --key <bearer key>
# or
FAULTLINE_MCP_URL=https://faultline.example.com/mcp FAULTLINE_MCP_KEY=<bearer key> npx -y @prashantthakur77/faultline-mcp
```

Running the server itself (FalkorDB, the API and the hosted MCP) is covered in the project's [MCP guide](https://github.com/Prashant-thakur77/Faultline/blob/main/docs/MCP.md).

## How it works

The package runs a local MCP server over stdio and forwards each request to the Faultline endpoint over Streamable HTTP. Tools, resources (`faultline://schema`, `faultline://queries`, `faultline://weights`) and prompts are the server's own, passed through unchanged. Every tool is read-only: the server reads FalkorDB through `GRAPH.RO_QUERY` as a per-tenant read-only user, with a timeout and a row limit, and never holds a write credential.

## Options

| Option | Environment | Default |
|---|---|---|
| `--url <https://host/mcp>` | `FAULTLINE_MCP_URL` | the public demo, `https://13-203-185-119.sslip.io/mcp` |
| `--key <bearer key>` | `FAULTLINE_MCP_KEY` | the demo's public read-only key (only with the default URL) |
| `--help`, `--version` | | |

Logs go to stderr; stdout is the MCP channel.

## License

Apache-2.0
