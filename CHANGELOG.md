# Changelog

All notable changes to Faultline. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.4.2] - 2026-10-18

### Honest to the last tool call
- `impact_bound` answers `unknown`, with the reason, when a suspect or the symptom is not a node of the tenant's graph (Q-NODE-EXISTS), instead of a zero flow that reads as "cannot carry the impact"; the gate sees G5 as not evaluable.
- The hosted MCP server lists only tools that can answer there: `repair_targets`, which reads the measurements of the run it is called in, stays with the agent (<!-- claim:repo.mcp_tools_hosted -->54<!-- /claim --> of <!-- claim:repo.mcp_tools -->62<!-- /claim --> hosted). Its documented examples run as written, and a "Reading a result" note explains the envelope.
- README: "Track 1 in five clicks" and "Track 3 in five clicks"; the showcase queries match the stored templates; the verification limits and the approver check stated exactly; the data-incident receipt names no branch or pull request.
- UI: accessible names only on focusable graph nodes; the explore page's in-text link is underlined.

## [1.4.1] - 2026-10-18

### The data incident, as a judge meets it
- The measured repair is ranked where the plan's own rule puts it (enabled production changes first, by predicted future and fix history; tracking after; disabled last), so it is the first option, not the fourth under two disabled ones; the plan's reason and the commit subject cut at a word, never mid-number.
- The proposal itself goes through the toolbox (`propose_repair` in the PLAN whitelist), so the run's log holds it beside the four reads it cites; `Q-REPAIR-TARGETS` marks the column it returns as seen.
- The static replay of the data incident is the recorded one that ends RESOLVED (it had kept an earlier take); the Pages build now refuses a replay bundle that does not match its committed example, and the export keeps the text of a template a recording cites that the catalogue has since renamed.
- A public example is recorded without this machine's on-call home, so it carries no learned preferences or guidelines of ours.
- "Run the data incident" sits beside the hero button on the home page.

## [1.4.0] - 2026-10-18

### The agent acts on the data incident too (track T1)
- **A measured data repair, no model needed.** After the gate confirms a data cutover, the run asks the warehouse whether the anomalous column's bad rows are one segment (one value of one text column) a power of ten off the healthy rows (`unit_shift_check`, recorded as Evidence with the numbers), asks the graph which transform writes the anomalous table nearest the cause along the proof path (`repair_targets`, Q-REPAIR-TARGETS, ordered in the engine), and wraps that column in a CASE for those rows only (`agent/unit_shift.py`, validated like any patch). The data_repair option is then enabled with the exact diff and a reasoning line that cites the evidence; two segments that fit equally are no answer.
- **Verified by the world.** Two-step approval of the exact diff, then the file on disk, the warehouse rebuilt on the incident's own data, the invariant suite and the KPI decide: the recorded S2 example ends <!-- claim:example.s2.verdict -->APPLIED<!-- /claim --> with <!-- claim:example.s2.invariants -->32/32<!-- /claim --> invariants, KPI anomaly ratio <!-- claim:example.s2.kpi_ratio -->0.933<!-- /claim -->, write-back <!-- claim:example.s2.writeback -->7/7<!-- /claim -->, final stage <!-- claim:example.s2.final_stage -->RESOLVED<!-- /claim -->; a wrong patch is still reverted (s5). The approval card shows the patch.

### The company brain answers what on-call actually asks (track T3)
- **Which runbook to follow.** A runbook kind: `runbooks_about` (one query, Q-RUNBOOK-ABOUT) returns a component's own runbooks and its symptoms', the symptom kind the question names first (slow → latency, errors → error rate, lag, a KPI jump), then the runbooks one failure hop away, with how often a learned runbook's fix worked and when a written one was last reviewed.
- **Who decided, for any decision.** `trace_decision` names the deciders of a decision and of its head (Q-DEC-WHO), so "who wrote ADR-009, are they still here?" is answered for a decision found by its id or name, not only through a component; "adr-21" reads as ADR-021. `decisions_about` also returns the policies that govern a component (a change freeze) and who put them in place (Q-POLICY-ABOUT).
- **Time, as people write it.** "in April 2026", "last June", "March 3, 2026", "2026-02", "spring 2026", "3 weeks ago", "last month": read at the period's first day, the date used stated in the answer; a month-long question says when a component changed hands within it.
- **Names, not only ids.** A component resolves from the words of its name in one query (Q-FIND-NAME: "the shipping quote calculator" is quote, "valkey" is cache); two-letter ids ("ad") resolve exactly, never fuzzily; knowledge-health answers lead with the kind of decay asked about (overdue runbooks, handovers without a runbook, decisions whose deciders have all left) and name the people who left; the policies that govern a component (a change freeze) and who put them in place (Q-POLICY-ABOUT); a "why" question is answered from the documents when two indexes agree on the source.
- **Measured blind, twice.** Two new blind sets of 40 questions, each written by an agent that never saw the brain and pre-registered before its one scoring: set 3 after the runbook and decision work <!-- claim:brain_blind.s3.m22_runbooks.correct -->29<!-- /claim -->/<!-- claim:brain_blind.s3.m22_runbooks.questions -->40<!-- /claim --> (set 2 after the fact: <!-- claim:brain_blind.s2.m22_runbooks.correct -->28<!-- /claim -->/40, from 24), then set 4 after the names, policies and why-questions work <!-- claim:brain_blind.s4.m22_names.correct -->36<!-- /claim -->/<!-- claim:brain_blind.s4.m22_names.questions -->40<!-- /claim -->; the sets 1 to 3 re-scored after the fact: <!-- claim:brain_blind.s1.m22_names.correct -->38<!-- /claim -->, <!-- claim:brain_blind.s2.m22_names.correct -->39<!-- /claim --> and <!-- claim:brain_blind.s3.m22_names.correct -->39<!-- /claim --> of 40; the development sets stay at <!-- claim:brain.correct -->33<!-- /claim -->/33 and <!-- claim:brain_para.correct -->31<!-- /claim -->/33.

## [1.3.1] - 2026-10-18

### The gate, tighter
- G6 also counts a rival the gate already confirmed as a competitor, and reads who set a hypothesis's current status (`status_by`), so no investigator, however it writes, can clear a rival; two new mutants (G6 and the tool's refusal) are killed, <!-- claim:mutation.killed -->43<!-- /claim --> of <!-- claim:mutation.mutants -->43<!-- /claim --> in all.
- Seed-time chunking reads the documents through the read-only wrapper.

### Docs
- Screenshots of the UDF libraries card and an agent's verdict note; the deep model-driving run's budget stop and the follow-up's scope are stated exactly; the clean-clone judge-check record at 004a6e8.

## [1.3.0] - 2026-10-18

### A model driving it stays honest (pre-registered, paid)
- With `claude-opus-5-5` driving the investigation and FalkorDB plus the gate deciding: right cause <!-- claim:llm_product.decisive.all.right_cause -->40<!-- /claim -->/<!-- claim:llm_product.decisive.all.cases -->40<!-- /claim --> and <!-- claim:llm_product.decisive.all.wrong_confident -->0<!-- /claim --> confident wrong blames on the decisive bench, where the same model alone blamed an innocent change <!-- claim:llm_deep.decisive.all.wrong_confident -->7<!-- /claim --> times (`evals/llm_product_bench.py`).
- That run found a way a model could move the gate on two-causes-in-a-chain worlds (marking the rival "eliminated" with an unrelated evidence id). Fixed the same hour: only the graph eliminates a competitor (no path, G2, or not enough flow, G5); a regression test replays what the model did; the re-run of those worlds with the same model: <!-- claim:llm_product.deep_fix.all.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:llm_product.deep_fix.all.cases -->8<!-- /claim -->.

### The site, checked by a user-style pass
- The hero scenario starts from the home page's button, every page has its own title, nothing scrolls sideways on a phone, graph labels stay readable at any zoom, the approval card says when GitHub is simulated, and the investigator picker explains the Claude option instead of calling it unavailable.
- The hosted MCP's `recall_notes` works without the engine credential; errors never carry the engine's host; the home page lists only runs that can still be opened; an anonymous run's in-app page no longer reads "delivery failed"; plain plurals and lists in the text people read; "Who owns X?" names the owning team and who is on call first.
- The For agents section on the home page is runnable as shown: the npm bridge, this site's own REST endpoint (whose answer now carries its Cypher, parameters and digest), and the whole proof-path query.


### The company brain reads document text (track T3)
- Document bodies (ADRs, runbooks, incident-channel chats, issues) are stored as `(:Chunk)` passages with `vecf32` embeddings and full-text, written at seed after everything else so no existing node id moves.
- `search_knowledge` (MCP, Q-KNOW-1) fuses seven index lists by reciprocal rank inside FalkorDB in one query, credits a document's text to the decision or runbook it produced, and returns the passage that matched with what each source concerns and who decided it.
- The brain falls back to document search only when no question kind matches and both index families agree on the best source.

### Shared agent notes, used by the agent itself (track T2)
- Investigations started from the API read the notes other agents left near the failing component (leads, never gate input) and leave their verdict or hand-off as a note; the note for a verified fix replies to that verdict with stance `confirms`. Eval arms keep notes off; a live test asserts the gate's outcome, cause and proof chain are the same with notes on and off.
- Private notes: `remember(private=true)` is recalled only by its author, in the same query that returns the shared notes.
- The containment min-cut refuses an oversized region before computing it.

### Preflight reads code
- A changed top-level constant with a literal value in Python, JS/TS, Go, Java/Kotlin or a properties/env/ini/toml file becomes a ChangeFact without a model, named by the rule keys decisions set on that component (`Q-DEC-KEYS`), so a code edit meets the same decision check as a config edit.

### The engine page shows the UDF libraries
- `/engine` lists FLEX and our own `faultline` library: state, pinned sha, the functions our queries call and the templates that call them (from `/api/status`, read from `GRAPH.UDF LIST` and the template catalogue).

## [1.2.0] - 2026-10-18

### FalkorDB does the ranking, with our own UDF library
- `deploy/udf/faultline-1.0.0.js`, loaded with `GRAPH.UDF LOAD` and pinned by sha256 like FLEX: the blast radius (`faultline.impact`), the notify list (`faultline.capImpact`, summed per team) and agent-note recall (`faultline.noteScore`) are scored and ordered inside FalkorDB, each in one read-only query. `faultline.round4` is Python's `round(x, 4)`, exact halves included, so engine and code agree on every number.
- The containment min-cut is computed in FalkorDB too: `algo.maxFlow` and the residual cut in one read-only query (`Q-CUT-3`: residual reachability as a list fixpoint in Cypher, then the edges that leave it). `graph/algo/maxflow.py` is now the test oracle, and the two agree on all <!-- claim:udf.eq.cut.nonempty -->197<!-- /claim --> non-empty cuts.
- Entity search is one query: the full-text and vector branches are merged by the engine in a `CALL { … UNION ALL … }` subquery (the template lint now allows `UNION` only inside a subquery, under the template's own final `LIMIT`).
- `evals/udf_equivalence.py` runs the previous Python code beside the engine on every node of both tenants, identical everywhere: blast radius <!-- claim:udf.eq.blast.nonempty_k -->198<!-- /claim -->/<!-- claim:udf.eq.blast.nonempty -->198<!-- /claim --> on every node with a non-empty blast radius (<!-- claim:udf.eq.blast.k -->7926<!-- /claim -->/<!-- claim:udf.eq.blast.n -->7926<!-- /claim --> calls in all), notify list <!-- claim:udf.eq.notify.nonempty_k -->195<!-- /claim -->/<!-- claim:udf.eq.notify.nonempty -->195<!-- /claim --> (on-call filled in <!-- claim:udf.eq.notify.with_oncall -->195<!-- /claim -->), search <!-- claim:udf.eq.find.nonempty_k -->170<!-- /claim -->/<!-- claim:udf.eq.find.nonempty -->170<!-- /claim --> non-empty answers (<!-- claim:udf.eq.find.k -->698<!-- /claim -->/<!-- claim:udf.eq.find.n -->698<!-- /claim --> calls), min-cut <!-- claim:udf.eq.cut.nonempty_k -->197<!-- /claim -->/<!-- claim:udf.eq.cut.nonempty -->197<!-- /claim --> non-empty cuts plus <!-- claim:udf.eq.cut.refused -->1<!-- /claim --> region both refused. The live tests keep the check.

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
- The company brain run beside FalkorDB's GraphRAG-SDK on a blind question set, with the same knowledge (`evals/graphrag_sdk_arm.py`).
- FalkorDB's own yardsticks: 250 tenant graphs on one engine with 0 cross-tenant leaks, p99 under 64 parallel investigators, a 1k to 10k scale curve with tail latency, and all 10 `algo.*` procedures against NetworkX.
- Upstream: a pull request to GraphRAG-SDK (#345, later closed in favour of the maintainers' fuller fix #348–#350), FalkorDB issues #3349, #3376 and #3377, new evidence on #3150 and #2502, and one private report.

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

[1.4.2]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.4.2
[1.4.1]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.4.1
[1.4.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.4.0
[1.3.1]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.3.1
[1.3.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.3.0
[1.2.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.2.0
[1.1.1]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.1.1
[1.1.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.1.0
[1.0.0]: https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.0.0
