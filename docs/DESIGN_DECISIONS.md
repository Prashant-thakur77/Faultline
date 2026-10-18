# Design decisions

A readable summary of the decisions that shape Faultline and why. The limits these decisions leave are in [HONEST_LIMITS.md](HONEST_LIMITS.md).

## 1. Engine pin

| Decision | Why |
|---|---|
| Pin `falkordb/falkordb:6.0.2` by digest, never `latest` | Smoke ran on both candidates. 6.0.2 passed every critical item. v4.22.0 ranked betweenness wrongly on a simple chain and let two workers own one task in a contention round. |
| 6.0.2 is the only acceptable 6.x | 6.0.0/6.0.1 silently dropped the `RO_QUERY` TIMEOUT. <!-- noclaim: engine versions --> |
| One `algo.maxFlow` form; the min-cut is computed in code from `edges`/`edgeFlows` | Both engines accept only the single-map form with node arrays. The positional forms shown in a FalkorDB news post do not exist. `min_cut` asserts that the cut's capacity equals the engine's max flow, or fails loudly. |
| Canonical procedure names in `graph/algo/registry.py`, resolved by smoke into `resolved.json` | Names are case-insensitive, but one spelling keeps templates and lint simple. `algo.betweenness` always gets a fixed sampling seed, because seed 0 is time-based. |
| Full-text in DDL form only, never on an attribute with a range index | The procedure form fails on 6.0.2, and an open 6.0 issue returns no rows for a range + full-text pair. <!-- noclaim: engine version --> |
| Smoke facts treated as contracts | `SSpaths` `pathCount` is a global top-k, so a full result means "possibly truncated" and gives UNKNOWN. The vector score is a distance. `EXISTS {}` is unsupported. The unique constraint is created asynchronously. |
| Engine bugs get a workaround, a lint rule and an upstream draft | Shapes that return wrong rows or crash the server are rejected by the template lint, not just avoided once. |

## 2. Gate design and G5 cap semantics

| Decision | Why |
|---|---|
| "No path, no claim": G2 is `algo.SPpaths` over `CHANGED\|GATES\|PROPAGATES_TO` | A claimed cause must be connected to the symptom by the graph, whatever the model says. |
| `cap` = criticality on service edges and end-to-end row share on lineage edges | rps share rejects true causes under synchronous fan-out. A "dependency share" was tried next and is not a sound bound under fan-in, call multiplicity or value share. Criticality and end-to-end row share make min(1, k × max flow), with k the number of distinct paths from the change to the symptom, an upper bound on what one cause can explain (plain max flow is the bound only when k = 1). |
| G5 is a joint test run to a fixpoint, per alert | A single-suspect bound wrongly rejects a true partial cause when two causes coexist. A suspect is eliminated only if the others together can still explain the impact. Only-jointly-sufficient means "multi-cause, not confident"; insufficient even together means abstain. |
| A deterministic competitor sweep at GATE | Every change in the window goes through G2 and G5 in code, with one `GateRun` each. Distractor rejection never depends on the model asking. |
| Origin test in the sweep | A path and capacity do not make a measured-healthy component the origin when another suspect's component is measured anomalous. Distractor scaling exposed the need. |
| The negative proof is three-valued | NO_INCIDENT needs measurements in band **and** an empty `SSpaths`. A timeout, an unknown id or an unready graph gives UNKNOWN, never "safe". |
| G1 is decided in the graph | `(:ToolCall)-[:SAW]->(n)` is written in the same query as the evidence, and G1 is a read-only template. No Python set is the source of truth. SAW is written only for ids the graph returned. |
| Proven vs inferred is decided by the gate | A claim without a G2 path is forced to "inferred", whatever the model labelled it. |
| No Python max-flow fallback, and the gate has no weakening branch | If `algo.maxFlow` failed, the answer would be to stop and ask, not to compute flows in Python. `FAULTLINE_ABLATION_RELAX_GATE` was removed from the package. |

## 3. FalkorDB is the only store

| Decision | Why |
|---|---|
| Lineage lives in FalkorDB | Lineage is ingested from a JSON fixture into FalkorDB. Every read is a template, and write-back is a graph write. |
| Run state lives in the graph; files are exports | Incidents, stages, tool calls, evidence, hypotheses, gate runs, plans and approvals are nodes. SSE is built from `StageEvent` reads. `events.jsonl` and `report.md` are generated. |
| An in-memory run state exists only for the ablation | `EphemeralRunState` can only be constructed when `FAULTLINE_DISABLE_GRAPH=true`, and it is the one lint-allowlisted in-memory state. |
| All similarity search runs in the FalkorDB vector index | Embeddings are computed locally and committed as model inputs. Vectors are written with `vecf32()`, and similarity is never computed in numpy. |
| `scripts/lint_single_store.py` in CI | It rejects other stores, numpy similarity, JSON state, hand-written graph algorithms and string-built Cypher, and now raw write Cypher in `evals/`. |
| Engine housekeeping outside the tenant RO wrapper is sanctioned | Readiness flags, constraint and index checks in `graph/copy.py` and `graph/writes.py` are bounded, fixed-text and never decision reads. |
| Ranking happens inside FalkorDB, with our own UDF library | The graph facts come from FalkorDB: reach and hops (`algo.BFS`, `algo.SSpaths`), bottleneck capacities, owners, index hits. The arithmetic that turns them into an order runs in the engine too, as our own UDF library (`deploy/udf/faultline-1.0.0.js`, loaded with `GRAPH.UDF LOAD` and pinned by sha256 like FLEX): `blast_radius` is one query scored by `faultline.impact` (tier × 1/(1+hops) × traffic), `notify_set` one query summing `faultline.capImpact` per owning team, and `find_entities` one `CALL { … UNION ALL … }` query that merges its full-text and vector branches by best score. The weights still come from `agent/weights.yaml`, passed as query parameters, because numbers come from code, never from a model. `evals/udf_equivalence.py` runs the previous Python code beside the engine, identical everywhere: blast radius <!-- claim:udf.eq.blast.nonempty_k -->198<!-- /claim -->/<!-- claim:udf.eq.blast.nonempty -->198<!-- /claim --> on every node with a non-empty blast radius (<!-- claim:udf.eq.blast.k -->7926<!-- /claim -->/<!-- claim:udf.eq.blast.n -->7926<!-- /claim --> calls in all), notify list <!-- claim:udf.eq.notify.nonempty_k -->195<!-- /claim -->/<!-- claim:udf.eq.notify.nonempty -->195<!-- /claim --> (on-call filled in <!-- claim:udf.eq.notify.with_oncall -->195<!-- /claim -->), search <!-- claim:udf.eq.find.nonempty_k -->170<!-- /claim -->/<!-- claim:udf.eq.find.nonempty -->170<!-- /claim --> non-empty answers (<!-- claim:udf.eq.find.k -->698<!-- /claim -->/<!-- claim:udf.eq.find.n -->698<!-- /claim --> calls), min-cut <!-- claim:udf.eq.cut.nonempty_k -->197<!-- /claim -->/<!-- claim:udf.eq.cut.nonempty -->197<!-- /claim --> non-empty cuts plus <!-- claim:udf.eq.cut.refused -->1<!-- /claim --> region both refused; `tests/live/test_udf_faultline.py` keeps that check. No path, reachability, ranking by structure or ownership lookup is computed in Python. |

## 4. Safety envelope

| Decision | Why |
|---|---|
| One read path: `GRAPH.RO_QUERY` + clamped TIMEOUT + literal LIMIT sent as n+1 | Truncation is detected, not silent. Errors are loud and typed (unavailable, timeout, not ready). The ablation guard runs on every call. |
| Templates first, linted | Literal LIMIT, `ORDER BY …, id`, bounded paths, CALL allowlist, no writes, no engine-bug shapes. |
| Guarded text2cypher as the last tier | Guard on masked text, `GRAPH.EXPLAIN` plan check, `RO_QUERY` with a short timeout. Results are evidence with `via:'text2cypher'`, and the tool requires naming the template that failed. |
| Two-step approval bound to a plan hash, exclusive in one query | Choosing is not approving. The approval moves the incident to EXECUTE in the same query, so a re-choice or a second approval cannot race. Reviewers are part of the hashed PR body. |
| Execute re-checks everything | It re-checks the approval status, the intent owner, the stored spec's hash and drift at GitHub main, refuses no-op changes, and only touches `faultline/fix-*` branches. |
| Verification is three-valued on two channels | Success is written only when APPLIED (W-WB-1). NOT_APPLIED and UNKNOWN use W-WB-2. A failed attempt is remembered as `ATTEMPTED`, never `RESOLVED_BY`. |
| intent → execute → reconcile by idempotency key | No cross-system transactions are claimed. The reconciler never re-executes an old approval and attributes only its own merged fix PR. |
| Mutation-test the safety invariants | Each invariant is broken in a scratch copy and a test must fail (`scripts/mutation_check.py`). |

The full table of what the agent cannot do is [SAFETY.md](SAFETY.md).

## 5. Memory

| Decision | Why |
|---|---|
| Recall is a graph query, never similarity alone | A vector seed on the incident's own embedding, then confirmation through a shared `Symptom` node. |
| Memory reorders; it never decides | It feeds only the smallest weight (`w_prior`), the prompt says precedents are not evidence, and gate verdicts are compared cold vs warm. |
| Decay never unpins an incident with an APPLIED fix; consolidation needs repeated APPLIED fixes | Derived runbooks come only from fixes that worked, with `DERIVED_FROM` provenance. |
| Forget runs with a receipt | The dry run lists exactly what one document alone produced. Execute needs that set's token. A receipt goes to `audit_<t>`, followed by proof that the vectors no longer come back and that the answer changed. |
| Learned remediation ordering reorders enabled options only | Beta-smoothed success rates per fix kind over incidents sharing a symptom, in Cypher. Disabled options never move, and the gate is not involved. |

## 6. Evals and pre-registration

| Decision | Why |
|---|---|
| Pre-register, keep the debug run, log every re-run | `evals/PREREGISTRATION.md` was written after one harness-debugging run, which is kept and never reported. Each later run states why it re-ran and that outcomes were unchanged. |
| Every published number is tagged and checked | `check_claims` compares each tagged number with `latest.json` and fails untagged measured-looking numbers. `RESULTS.md` is generated, never hand-edited. |
| Ablations that isolate the graph | A4 (FalkorDB off) fails closed. A3-noG5 switches off only the max-flow check. V is vector-only cosine in FalkorDB. N is naive recency. |
| LLM arms run only with an approved budget | They are skipped without an API key and an approved spending cap; a paid run writes a side file, so it can never replace the keyless results. |
| The preflight backtest is as-of and not re-tuned | Every historical PR is scored by the production formula as of its merge time through as-of templates, with a memory-term ablation. Negative results are reported. |

## 7. Tenancy and public-mode security

| Decision | Why |
|---|---|
| One graph per tenant, tenant-scoped derived graphs | `scratch_<t>_*`, `whatif_<t>_*` and `eval_<t>_*`, so an ACL key pattern can scope a read-only user to one tenant. |
| A per-tenant ACL user with a command allowlist, no `GRAPH.LIST` | Read-only comes from the command allowlist. `GRAPH.LIST` leaks every graph name to restricted users. |
| The hosted MCP binds a bearer key to one tenant and hosts no scratch-writing tools | Tools never take a graph name. The MCP service gets no engine credential. It refuses to start without keys. |
| Public mode | Choose and approve need the run's token (only its hash is stored). The approver must be an active person in the graph. Visitors' forget and preflight run on clean-room copies. There is no LLM without the operator key. Rate limits are per visitor plus global caps. |

## 8. Company-brain and routing features

Each feature is a template plus a tool, and each changes a decision or a reported fact.

| Feature | Template · tool | Decision |
|---|---|---|
| Who to notify | `Q-NOTIFY-2` · `notify_set` | Distinct from who fixes it: owners of the blast radius plus who is on call now |
| Why alerts missed it | `Q-CHAIN-MON` · `alert_coverage` | Per hop of the proven chain, advisory and after the verdict |
| Owner at the time, as-of beliefs, timeline | `Q-OWN-AT`, `Q-ASOF-1`, `Q-TIMELINE-1` | Read the `OWNED_AT`/`ON_CALL` windows and `SUPERSEDES` dates that were written but never read before |
| Knowledge health, hidden coupling | `Q-KH-1/2/3`, `Q-COUPLE-1` | The graph points at its own stale knowledge and probably-missing edges. Never evidence for the gate. |
| Learned remediation ordering, residue check | `Q-REM-1`, `Q-RESIDUE-1` | Reorder options; report anomalies the confirmed cause does not explain |
| Graph schema for the model | `Q-SCHEMA-1..4` · `graph_schema` | Grounds text2cypher; a drift check against the declared model |

Dropped or deferred, with reasons: `OVERRIDDEN_BY` (G8 never blocks, so it would be decoration); preflight formula changes (need a new pre-registration).
