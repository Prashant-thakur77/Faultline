# Faultline by the numbers

Every number on this page is read from [`evals/results/latest.json`](../evals/results/latest.json) and checked by `make claims`; a number that drifts from the results file fails the build. The charts are drawn from the same file by `scripts/gen_charts.py`. The method behind each figure, its pre-registration and its limits are in [EVALS.md](EVALS.md), [evals/PREREGISTRATION.md](../evals/PREREGISTRATION.md) and [evals/RESULTS.md](../evals/RESULTS.md).

Everything here is keyless: the deterministic investigator, no API key, no LLM spend. The LLM arms have not been run, so this page makes no LLM-vs-graph claim.

## Scorecard

| What is measured | Faultline | What it is compared with |
|---|---|---|
| Right verdict on the scenario suite (confirm the true cause, or abstain when there is none) | <!-- claim:arm.A3.outcome_correct_rate -->100%<!-- /claim --> of <!-- claim:arm.A3.trials -->24<!-- /claim --> trials | telemetry only <!-- claim:arm.T.outcome_correct_rate -->62.5%<!-- /claim -->, vector similarity <!-- claim:arm.V.outcome_correct_rate -->25%<!-- /claim -->, naive recency <!-- claim:arm.N.outcome_correct_rate -->0%<!-- /claim --> |
| Confidently blaming the wrong change | <!-- claim:arm.A3.false_blame_rate -->0%<!-- /claim --> | telemetry only <!-- claim:arm.T.false_blame_rate -->20%<!-- /claim -->, vector similarity <!-- claim:arm.V.false_blame_rate -->60%<!-- /claim -->, naive recency <!-- claim:arm.N.false_blame_rate -->100%<!-- /claim --> |
| Adversarial deep bench (fresh seed; causes 1–4 hops upstream, look-alike deploys on the path and downstream) | <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds | it abstains on <!-- claim:deep.fresh.all.abstained -->89<!-- /claim --> of them instead of guessing |
| Gate bench (generated cases, verdict fixed before the run) | <!-- claim:gate_bench.correct -->100<!-- /claim -->/<!-- claim:gate_bench.cases -->100<!-- /claim --> development, <!-- claim:gate_bench_heldout.correct -->100<!-- /claim -->/<!-- claim:gate_bench_heldout.cases -->100<!-- /claim --> held out | |
| The graph is load-bearing | FalkorDB off (arm A4) confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes: it fails closed | max-flow check off (A3-noG5): right verdicts fall to <!-- claim:arm.A3-noG5.outcome_correct_rate -->87.5%<!-- /claim -->, look-alikes rejected <!-- claim:arm.A3-noG5.distractors_rejected_rate -->60%<!-- /claim --> |
| Safety invariants under mutation | <!-- claim:mutation.killed -->41<!-- /claim --> of <!-- claim:mutation.mutants -->41<!-- /claim --> deliberately broken invariants caught by a test | |
| Context for any agent: rank of the true cause, 30 unrelated deploys in the window (MRR) | <!-- claim:ctx.busy30.b1000.GA.mrr -->0.6598<!-- /claim --> | vector RAG <!-- claim:ctx.busy30.b1000.V.mrr -->0.4226<!-- /claim -->, recency <!-- claim:ctx.busy30.b1000.R.mrr -->0.0768<!-- /claim --> |
| Company brain (our question set) | <!-- claim:brain.correct -->33<!-- /claim -->/<!-- claim:brain.questions -->33<!-- /claim --> correct; <!-- claim:brain.unanswerable_honest -->6<!-- /claim -->/<!-- claim:brain.unanswerable -->6<!-- /claim --> unanswerable questions declined with no citation; p50 <!-- claim:brain.ms_p50 -->10.2<!-- /claim --> ms | |
| Many responders, one incident: <!-- claim:contention.responders -->24<!-- /claim --> approvals of the same plan at once | <!-- claim:contention.same.accepted -->1<!-- /claim --> accepted, <!-- claim:contention.same.refused -->23<!-- /claim --> refused, <!-- claim:contention.same.prs -->1<!-- /claim --> PR | |
| Crash between execute and verify (SIGKILL, restart, reconcile) | exactly once = <!-- claim:chaos.exactly_once -->True<!-- /claim -->, <!-- claim:chaos.prs_after_reconcile -->1<!-- /claim --> PR after reconcile | a naive retry without the idempotency key merged <!-- claim:chaos.control_merged_prs -->2<!-- /claim --> PRs |
| Work claims under contention (<!-- claim:s13.workers -->16<!-- /claim --> workers, <!-- claim:s13.rounds -->100<!-- /claim --> rounds) | <!-- claim:s13.rounds_one_owner -->100<!-- /claim --> rounds with exactly one owner, <!-- claim:s13.lost_updates -->0<!-- /claim --> lost updates | |
| Scale: <!-- claim:scale.10k.services -->10000<!-- /claim --> services (<!-- claim:scale.10k.nodes -->296261<!-- /claim --> nodes, <!-- claim:scale.10k.edges -->1097675<!-- /claim --> edges) | right cause = <!-- claim:scale.10k.correct -->True<!-- /claim -->, whole run <!-- claim:scale.10k.run_s -->6.35<!-- /claim --> s, gate path query `Q-GATE-1` engine p50 <!-- claim:scale.10k.Q-GATE-1.engine_ms_p50 -->7.572<!-- /claim --> ms | at 1k services: <!-- claim:scale.1k.Q-GATE-1.engine_ms_p50 -->1.069<!-- /claim --> ms |
| Investigation time, scenario suite | p50 <!-- claim:arm.A3.seconds_p50 -->0.75<!-- /claim --> s, p95 <!-- claim:arm.A3.seconds_p95 -->1.54<!-- /claim --> s | |

## Against other approaches

![Right outcome on the scenario suite](media/charts/outcome.svg)

![Confidently blaming the wrong change](media/charts/false_blame.svg)

The arms share one engine, one seed and one grader; only the decision rule changes:
- **Naive recency** blames the latest change in the window.
- **Vector similarity** blames the change whose text is closest to the alert (FalkorDB's vector index; the graph is not walked).
- **Telemetry only** blames the change on the component with the largest error rise.
- **Faultline** confirms a change only when `algo.SPpaths` returns a path from it to the symptom, `algo.maxFlow` shows the path can carry the observed impact, and the rest of the gate (timing, origin, rivals, agreement) holds. Otherwise it abstains.

Telemetry-only is the strongest baseline and still blames an innocent deploy whenever the deploy sits on a component that is merely downstream of the real break: it sees the symptom, not the direction of failure.

## Why FalkorDB: what the graph engine itself contributes

**Take its algorithms away and the decisions get worse.** On the <!-- claim:ladder.full.cases -->100<!-- /claim --> held-out gate-bench worlds, one capability is removed at a time and everything else runs as shipped ([evals/ladder.py](../evals/ladder.py)):

| Capability | Correct verdicts | Confident wrong blames |
|---|---|---|
| Full product: `algo.SPpaths` + `algo.maxFlow` | <!-- claim:ladder.full.correct -->100<!-- /claim --> | <!-- claim:ladder.full.wrong_confident -->0<!-- /claim --> |
| `algo.maxFlow` removed (no capacity bound) | <!-- claim:ladder.no_maxflow.correct -->80<!-- /claim --> | <!-- claim:ladder.no_maxflow.wrong_confident -->0<!-- /claim --> |
| `algo.SPpaths` replaced by mere connectivity (`algo.WCC`) | <!-- claim:ladder.no_sppaths.correct -->76<!-- /claim --> | <!-- claim:ladder.no_sppaths.wrong_confident -->0<!-- /claim --> |
| Both removed | <!-- claim:ladder.neither.correct -->56<!-- /claim --> | <!-- claim:ladder.neither.wrong_confident -->0<!-- /claim --> |

![Take FalkorDB's algorithms away and the answers get worse](media/charts/ladder.svg)

The gate stays safe on every rung (it abstains rather than guess); what each algorithm buys is the ability to *decide*. Counted only over the worlds that have a true cause, the right cause is blamed in <!-- claim:ladder.full.b.right_cause -->65<!-- /claim --> of <!-- claim:ladder.full.b.confirm_cases -->65<!-- /claim --> with both algorithms and <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim --> without them. That is the load-bearing test: the product is measurably worse without the graph engine, and with FalkorDB switched off entirely (arm A4) it confirms nothing.

**The same graph questions, with identical answers to recursive SQL.** On a 1,000-service graph ([evals/perf_vs_flat.py](../evals/perf_vs_flat.py)), each lookup was run as the product runs it and as DuckDB recursive SQL over the same edge table; the answers were checked equal on every instance:

| Lookup (1k services, p50) | FalkorDB, product round trip | FalkorDB engine time | DuckDB recursive SQL (in-process) |
|---|---|---|---|
| Shortest causal path (`algo.SPpaths`) | <!-- claim:perf.1k.shortest_causal_path.falkordb_rt_p50 -->0.211<!-- /claim --> ms | <!-- claim:perf.1k.shortest_causal_path.falkordb_engine_p50 -->0.023<!-- /claim --> ms | <!-- claim:perf.1k.shortest_causal_path.sql_p50 -->1.284<!-- /claim --> ms |
| Blast radius (`algo.BFS` reach set) | <!-- claim:perf.1k.reach_set.falkordb_rt_p50 -->0.394<!-- /claim --> ms | <!-- claim:perf.1k.reach_set.falkordb_engine_p50 -->0.138<!-- /claim --> ms | <!-- claim:perf.1k.reach_set.sql_p50 -->1.559<!-- /claim --> ms |
| Hop distances | <!-- claim:perf.1k.hop_distance.falkordb_rt_p50 -->0.217<!-- /claim --> ms | <!-- claim:perf.1k.hop_distance.falkordb_engine_p50 -->0.03<!-- /claim --> ms | <!-- claim:perf.1k.hop_distance.sql_p50 -->1.565<!-- /claim --> ms |

![Same graph questions, same answers: FalkorDB against recursive SQL](media/charts/vs_sql.svg)

Both answer in milliseconds at this size, so this is not a speed claim: the point is that the graph engine gives the same answers natively, with the product's own round trip lower even though DuckDB runs in-process and computes only the path length (`Q-GATE-1` also returns the paths). What SQL cannot do at all is the capacity bound: max flow, behind G5, has no SQL equivalent.

**Fresh enough to act on.** An alert written by the engine user is seen by the read-only decision query that consumes it in p50 <!-- claim:perf.fresh.alert.p50_ms -->0.602<!-- /claim --> ms; <!-- claim:perf.fresh.alert.first_read_saw_it -->50<!-- /claim --> of <!-- claim:perf.fresh.alert.writes -->50<!-- /claim --> writes were visible on the first read.

**One engine for everything the agent knows.** Topology, telemetry windows, evidence, gate runs, plans, approvals, write-back, memory vectors (`vecf32` + vector index) and documents (full-text index) all live in FalkorDB, one graph per tenant with its own read-only ACL user; clean rooms are `GRAPH.COPY`s. `scripts/lint_single_store.py` fails CI if any other store creeps in.

**Giving back.** Building on the engine surfaced engine issues, each reduced to a minimal reproduction with a workaround and a lint rule so the product never depends on the broken shape: [docs/upstream/](upstream/) (the most serious is a read-only query that crashes the server on 6.0.2).

## Context for agents

![Is the true cause near the top of the agent's context?](media/charts/context_mrr.svg)

`context_pack` (MCP tool and `POST /api/context_pack`) gives any agent a token-budgeted briefing ranked by the graph. With 30 unrelated deploys in the window, the graph ranking puts the true cause far higher than vector retrieval or recency over the same data. Vector RAG and recency also never surface the decisions a change would contradict; the graph pack does.

## What makes these numbers hard to fake

- **Pre-registered.** Arms, metrics and stopping rules were written down before the runs ([PREREGISTRATION.md](../evals/PREREGISTRATION.md)); later changes are dated amendments, and failed runs are kept.
- **Held out.** The gate bench has a second set generated from a seed nobody tuned against.
- **Adversarial.** The deep bench was built to break the gate (look-alikes downstream of an unchanged break, two-path worlds). Its first version found a real hole in the shipped gate; the fix is in the code and the numbers above are from the fixed gate on a fresh seed.
- **Mutation-tested.** Each safety invariant is broken on purpose in a scratch copy, and a test must fail.
- **Checked in CI.** `make claims` fails on any number on this page, the README or the docs that drifts from the results file.

## Reproduce

```bash
make setup && make judge-check      # keyless; prints PASS
make eval && make results           # every arm and bench → evals/results/run_NNNN.json, latest.json, RESULTS.md
uv run python scripts/gen_charts.py # the charts on this page
make claims                         # every number on this page against latest.json
```

## What these numbers do not show

- **Synthetic worlds.** The topology is shaped like the OpenTelemetry Demo and the incidents are generated; real production incidents are untested.
- **Our own benches.** "Zero confident wrong blames" is bounded by what the benches generate; the deep bench widened that, and it still is not the open world.
- **No LLM comparison yet.** The LLM arms need an API key and an approved budget.

The full list is in [HONEST_LIMITS.md](HONEST_LIMITS.md).

How current products approach the same problem, with sources: [LANDSCAPE.md](LANDSCAPE.md).
