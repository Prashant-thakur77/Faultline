# Changelog

All notable changes to Faultline. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-16

First public release: the version deployed at [13-203-185-119.sslip.io](https://13-203-185-119.sslip.io) and submitted to Graph Hacks (tracks T1 and T3). Measured results are in [evals/RESULTS.md](evals/RESULTS.md); the README quotes only numbers checked against `evals/results/latest.json`.

### Investigation and the evidence gate
- Per-tenant FalkorDB operational context graph (topology, lineage, deploys, flags, telemetry windows, people, decisions, runbooks) on the pinned engine `falkordb/falkordb:6.0.2`, by digest.
- Evidence gate G1–G8: a cause is confirmed only when `algo.SPpaths` returns a path from the change to the symptom, `algo.maxFlow` shows it can carry the observed impact, the timing and origin fit, rivals are ruled out and specialists agree. Otherwise the run abstains.
- Five deterministic specialist investigators and a crew of 12 least-privilege roles whose claims, hand-offs and tool calls are recorded in the graph, with provenance from each verdict to the call that produced its evidence.

### Action
- Smallest containment from the max-flow min-cut, each option tried first on its own `GRAPH.COPY`.
- Who fixes it: harmonic centrality over code, incident and on-call history; escalation path from a minimum spanning forest.
- One human-approved action with two-step approval bound to a plan hash; intent, execute, reconcile with an idempotency key; three-valued verification (APPLIED, NOT_APPLIED, UNKNOWN), where UNKNOWN goes to a human and never records success.
- Write-back into the same graph and warm recall for the next incident.

### Same graph, more uses
- Preflight: a pre-deploy gate that scores a PR against the graph, including a guard for changes that reinstate a reversed decision.
- Company brain: who owns, knows and decided what, with cited node ids; forget with a receipt.
- Graph-ranked context packs for any agent, and read-only MCP tools (stdio and hosted HTTP with per-tenant bearer keys).

### Product and operations
- Web app: incident room, preflight, memory, brain, explore (FalkorDB canvas), break-the-graph playground and a recorded replay player; a static replay site for GitHub Pages.
- Live deployment: one VM with Docker Compose (FalkorDB never exposed, ACL users per tenant, Caddy with TLS), public mode with run tokens, rate limits and no LLM spend.
- Keyless reproduction: `make setup && make judge-check` prints PASS with no API key.

[1.0.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.0.0
