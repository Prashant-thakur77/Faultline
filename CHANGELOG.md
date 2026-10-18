# Changelog

All notable changes to Faultline. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### FalkorDB does the ranking, with our own UDF library
- `deploy/udf/faultline-1.0.0.js`, loaded with `GRAPH.UDF LOAD` and pinned by sha256 like FLEX: the blast radius (`faultline.impact`), the notify list (`faultline.capImpact`, summed per team) and agent-note recall (`faultline.noteScore`) are scored and ordered inside FalkorDB, each in one read-only query. `faultline.round4` is Python's `round(x, 4)`, exact halves included, so engine and code agree on every number.
- Entity search is one query: the full-text and vector branches are merged by the engine in a `CALL { … UNION ALL … }` subquery (the template lint now allows `UNION` only inside a subquery, under the template's own final `LIMIT`).
- `evals/udf_equivalence.py` runs the previous Python code beside the engine on every node of both tenants: blast radius identical <!-- claim:udf.eq.blast.k -->7915<!-- /claim -->/<!-- claim:udf.eq.blast.n -->7915<!-- /claim -->, notify list <!-- claim:udf.eq.notify.k -->7915<!-- /claim -->/<!-- claim:udf.eq.notify.n -->7915<!-- /claim -->, search <!-- claim:udf.eq.find.k -->698<!-- /claim -->/<!-- claim:udf.eq.find.n -->698<!-- /claim --> (<!-- claim:udf.eq.texts -->349<!-- /claim --> texts × two tenants × five label filters in rotation). The live tests keep the check.

### Shared agent notes (track T2)
- `remember` and `recall_notes`: agents leave each other leads about components in `agentmem_<tenant>`, a `GRAPH.COPY` of the topology plus the notes, written only by a new `mem_<tenant>` ACL user whose one key is that graph. One atomic query checks the components, the reply target and a daily quota on the engine clock; one read-only query recalls notes by meaning and by hops from a component. Notes are never evidence. After a verified fix the API leaves a verdict note for the next agent. The public demo stays read-only.
- Three new engine constraints on notes (UNIQUE id; MANDATORY author, kind, text, time, expiry; MANDATORY reply stance).

### Docs
- A glossary of the README's own terms; the T3 track-fit row leads with the blind result.

## [1.1.1] - 2026-10-18

### Use it
- An npm package, [`@prashantthakur77/faultline-mcp`](https://www.npmjs.com/package/@prashantthakur77/faultline-mcp): `npx -y @prashantthakur77/faultline-mcp` gives any stdio MCP client (Claude Desktop, Cursor, Claude Code) Faultline's read-only graph tools, on the live demo by default or on your own server.
- A one-command quickstart, `deploy/quickstart.yml`: FalkorDB, the demo graphs, the API, the MCP endpoint and the UI from images published on ghcr.io by a new release workflow.

### Fixed
- Stored evidence and tool-call payloads are always valid JSON: they were cut at a fixed length, which could end inside a string and break every later read of that run's plan.
- The hosted MCP endpoint runs the current build (its image was not rebuilt by the deploy script); it served 51 tools at this release. <!-- noclaim: the count at 1.1.1, not the current one -->
- The gate's G4 upstream checks record the exact parameters they ran with, so a replay re-runs them.

### Video
- The narration fills the waits while real pull requests merge (what "APPLIED" means, and the pager's channels: in the app, email, Telegram, PagerDuty), and a new scene breaks the graph live on `/playground`. 4:25, recorded in one real take.

## [1.1.0] - 2026-10-18

The version deployed at [13-203-185-119.sslip.io](https://13-203-185-119.sslip.io) at submission (tracks T1, T3 and T2). Every number below is checked against `evals/results/latest.json` where the README quotes it.

### On call
- A real pager: in-app, webhook (Slack-compatible), Telegram, PagerDuty Events v2 and email through AWS SES. One message per destination per incident wave, signed expiring acknowledgement links, escalation along the graph's `algo.MSF` tree, hand-offs and a shift report, all stored in the graph.
- Standing approvals: after a verified fix, the on-call can grant a one-use, expiring contract for exactly that repeat; the gate still has to prove the cause, the fix runs and verifies, and nobody is woken. A scripted, pre-registered on-call night checks it end to end, with five negative cases.
- A Telegram bot whose cards are edited in place as the incident moves; approval from Telegram needs the plan's own code typed back by a mapped person.

### Learning from the people who use it
- Recency-decayed preferences reorder plan options, rejections with a reason become proposed guidelines (promote or dismiss), the people who actually answer are paged first, a standing approval is suggested after repeated verified fixes, and anyone's learned influence can be forgotten with a receipt. Only trusted actors teach it, and it never changes what the gate accepts.

### FalkorDB in depth
- MANDATORY and UNIQUE constraints, a per-query memory cap, a tuned vector index (recall@10 <!-- claim:vector.recall_at_10.tuned -->1.0<!-- /claim --> on <!-- claim:vector.queries -->702<!-- /claim --> queries), `WAITAOF` before a write-back counts, change-freeze policies on temporal values, the engine's own telemetry stream and `GRAPH.MEMORY USAGE` behind a new `/engine` page, and a production engine network with no internet egress.

### Evidence
- FaultBench-OTel: the real OpenTelemetry Demo, its own fault flags and real telemetry (pre-registered).
- The company brain against FalkorDB's GraphRAG-SDK on a blind question set (the SDK won; reported as a limit).
- FalkorDB's own yardsticks: 250 tenant graphs on one engine with 0 cross-tenant leaks, p99 under 64 parallel investigators, a 1k to 10k scale curve with tail latency, and all 10 `algo.*` procedures against NetworkX.
- Upstream: a fix to GraphRAG-SDK (#345), FalkorDB issues #3349, #3376 and #3377, new evidence on #3150 and #2502, and one private report.

### Video and docs
- A 4:25 narrated video recorded in one real take, with two real pull requests; "Proof at a glance" and "Why FalkorDB, in numbers" in the README; refreshed screenshots.

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

[1.1.1]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.1.1
[1.1.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.1.0
[1.0.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.0.0
