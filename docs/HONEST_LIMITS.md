# Scope, assumptions and engine caveats

This page says what is real and what is synthetic, the assumptions the gate makes, what the public demo does not protect, and the caveats of the pinned FalkorDB engine. Every measured number on this page is tagged and checked against `evals/results/latest.json` (`make claims`).

## 1. What is real and what is not

| Part | Status | Where it is said |
|---|---|---|
| FalkorDB, every query and algorithm, the agent loop, the gate | Real | README "What's real vs synthetic" |
| The data pipeline (DuckDB warehouse + invariant suite) used to verify data repairs | Real (the system under observation) | `pipeline/`, `backend/faultline/warehouse.py` |
| Org, people, history, ADRs, runbooks, postmortems, chats, issues, SLOs, customers | Synthetic, seeded and deterministic (`ingest/org_gen.py`, `ingest/history.py`, `ingest/obligations.py`, `data/gen/docs/`, `ingest/globex/`) | README "What's real vs synthetic" |
| Service topology | Shaped on the OpenTelemetry Demo (`data/topology/otel-demo.yaml`); globex is generated (`data/topology/globex.yaml`). Its history is synthetic: a quarter of the calls are dated to a past PR that introduced them (`ingest/topology_history.py`) | same |
| Service telemetry | Simulated in every bench but one: `sim/telemetry.py` writes `MetricWindow` nodes from the topology and the scenario's effects. FaultBench-OTel uses the real OpenTelemetry Demo's measured span-metric error rates (`ingest/observed.py`) | same |
| GitHub | Simulated in every eval run and on the public site (`actions/github.py::SimGitHub`). The real path (`RealGitHub`, `FAULTLINE_GITHUB=real`) runs on every real video take: each of the [pull requests on faultline-demo-infra](https://github.com/Prashant-thakur77/faultline-demo-infra/pulls?q=is%3Apr) was opened, merged after the two-step approval and verified APPLIED (the first is [PR #1](https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1)). These are demonstrations, not a measurement. | README "What's real vs synthetic" |
| Scenarios and brain questions | Self-authored (`data/scenarios/scenarios.yaml`, `data/brain/`) | [evals/RESULTS.md](../evals/RESULTS.md) |
| The investigator behind the keyless numbers | The deterministic `BaselineInvestigator`, not an LLM (`agent/loop.py`). The LLM arms (A0, A1, A3L) are a separate, small comparison with one model: A0 and A1 three trials per scenario, A3L one per scenario on all 8 | README "Scope and assumptions" |

## 2. Design assumptions

- **G5 is an upper bound under modelled capacities.** Service `cap` is criticality, set per edge in the topology file. Lineage `cap` is an end-to-end row share computed once by SQL. Neither is learned from traffic. ([EXPLAINER.md](EXPLAINER.md), `docs/design/scenario_numbers.md`)
- **Single cause by default.** Two causes that are only jointly sufficient give "multi-cause, not confident", never a confident claim.
- **G8 never blocks.** It attaches contradicted decisions. A reviewer can answer one for a single change (intentional / accidental / discuss, two-step, `(:Override)-[:OVERRIDES]->(:Decision)`): an intentional answer turns it into an accepted deviation for that change in G8 and preflight from the next gate run on; it never edits the decision itself, which is what a superseding ADR is for.
- **pageRank orders; it does not decide.** Verdicts come from the deterministic sweep, so pageRank changes the investigation order and tool use, not the outcome.
- **Abstention infers, never confirms.** When no change explains the symptom (S12), the upstream origin is reported as inferred and unconfirmed, and only tracking is offered.

## 3. Public demo and security

From [SECURITY.md](../SECURITY.md), "What is NOT protected (accepted for a demo)":
- **The approver identity is client-asserted.** The approver must be an active person in the graph; against real GitHub the operator's approver key is also required.
- **Re-arm is open** (rate-limited) and restores the seeded data for all visitors.
- **Brain history** is readable by anyone who knows a pseudonymous session id.

## 4. Engine caveats (pinned `falkordb/falkordb:6.0.2`)

From [FALKORDB_COMPAT.md](FALKORDB_COMPAT.md) and [docs/upstream/](upstream/):
- **Missing algorithms:** 6.0.x has no A*, k-shortest paths, Leiden or Louvain. Incident families use `algo.labelPropagation`. <!-- noclaim: engine version -->
- **Full-text:** the procedure form fails on 6.0.2, so only the DDL form is used.
- **Workarounds for engine bugs:** OPTIONAL MATCH after an aggregating WITH, an `SSpaths` aggregation that crashes the server, several pattern-comprehension shapes, WITH/UNWIND followed by two MATCH clauses, and a CALL subquery after OPTIONAL MATCH that filters a node before binding it (silent empty results). Each has a workaround, a template-lint rule, and a drafted upstream report in `docs/upstream/`. Compose restarts the engine if it crashes.
- **Atomicity is per query.** Cross-system steps use intent → execute → reconcile with an idempotency key. We claim no cross-system transactions.
- **`GRAPH.LIST` leaks graph names** to restricted users, so the per-tenant ACL user excludes it.
- **Only production isolates the engine from the internet.** The
  production compose puts FalkorDB on an internal Docker network with no route out (`scripts/egress_check.py`,
  `tests/live/test_egress.py`); the development compose does not (it publishes the engine on loopback, which an internal
  network cannot do), so on a developer machine the engine can still fetch from the internet.
- **Change freezes use a fixed UTC offset.** FalkorDB 6.0.2 has no time zones, so a policy's window does not follow
  daylight-saving changes. `.dayOfWeek` returns 0 on Sunday on 6.0.2; the freeze template reads it as 7. The product
  evaluates the window on the engine clock at preflight time, which stands in for the merge time.
- **Durable verification costs about a second.** WAITAOF waits for the next once-a-second fsync (appendfsync everysec)
  after the write-back; a timeout (5 s) is UNKNOWN and escalates. A replica (`WAIT`) is not used.
- **Node ids are not engine-unique.** A UNIQUE constraint over `:Node` (every node) makes every insert cost time
  proportional to the graph's size on 6.0.2 (draft `upstream/25`), so only Run and Intent ids are UNIQUE; every other
  writer MERGEs by id, and `Node.id` is MANDATORY.
- **The per-query memory cap is sized for these workloads.** 256 MB was active through the 1k to 10k scale curve
  and no template hit it.
- **Deleted graphs keep their memory until restart.** On the pinned 6.0.2, deleting a large graph (the 10k scale tenant) left `used_memory` near 2 GB; MEMORY PURGE did not return it. `make compact` (AOF rewrite + restart, graphs kept) does, and `make eval` refuses to start above 35% of maxmemory. <!-- noclaim: a configured threshold (evals/harness.py EVAL_MAX_START_PRESSURE), not a measured result -->
