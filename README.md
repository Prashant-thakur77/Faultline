<p><picture><source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/faultline-mark-light.svg"><img src="frontend/public/brand/faultline-mark.svg" width="64" height="64" alt="Faultline logo: a block split by an ember fault line"></picture></p>

# Faultline: no path, no claim

**An on-call agent that won't blame a change until FalkorDB returns the causal path, and won't keep a suspect the graph shows cannot carry the impact.** The model suggests; a read-only query decides.

[![CI](https://github.com/Prashant-thakur77/Faultline/actions/workflows/ci.yml/badge.svg)](https://github.com/Prashant-thakur77/Faultline/actions/workflows/ci.yml) [![Live demo](https://img.shields.io/badge/live%20demo-online-2ea44f)](https://13-203-185-119.sslip.io) [![FalkorDB 6.0.2, pinned by digest](https://img.shields.io/badge/FalkorDB-6.0.2%20pinned%20by%20digest-ff4e00)](docs/FALKORDB_COMPAT.md) [![judge-check: keyless PASS](https://img.shields.io/badge/make%20judge--check-keyless%20PASS-2ea44f)](#reproduce-it)

**Tracks:** T1 Agents That Act on Connected Data ([how one incident flows](#how-one-incident-flows)) · T3 Company Brain ([memory and brain](#memory-company-brain-preflight-coordination)) · T2 Agent Memory & Coordination ([learning from the people who use it](#learns-from-the-people-who-use-it-t2))

![The gate at work: a no-path rejection (G2), a max-flow rejection (G5), then the proof path](docs/media/hero.gif)

**Live demo: [13-203-185-119.sslip.io](https://13-203-185-119.sslip.io)** (keyless: deterministic investigator, simulated GitHub; press Re-arm to reset it) · **Hosted MCP:** `https://13-203-185-119.sslip.io/mcp` with a public read-only demo key ([try it in one command](docs/MCP.md#try-the-hosted-server-now-public-demo-key)) · **Recorded replay (no backend):** [prashant-thakur77.github.io/Faultline](https://prashant-thakur77.github.io/Faultline/) · **Release:** [v1.0.0](https://github.com/Prashant-thakur77/Faultline/releases/tag/v1.0.0) ([changelog](CHANGELOG.md))

**Demo video (5:14, narrated):** [watch or download](https://github.com/Prashant-thakur77/Faultline/releases/download/v1.0.0/faultline-demo.mp4) (also at [`docs/media/demo.mp4`](docs/media/demo.mp4), captions in [`docs/video_captions.srt`](docs/video_captions.srt)). Chapters: 0:30 the thesis · 0:53 how FalkorDB decides, in 3D ([live `/explainer`](https://13-203-185-119.sslip.io/explainer), drawn from the hero incident's recorded FalkorDB results) · 2:56 the live incident · 3:38 a real PR, APPLIED · 4:23 the numbers. The 2 a.m. problem first, then how FalkorDB makes "no path, no claim" possible, then the product in one take on the GPU: the incident room, a real pull request on [faultline-demo-infra](https://github.com/Prashant-thakur77/faultline-demo-infra/pulls?q=is%3Apr) merged after the two-step approval and verified APPLIED, preflight, the company brain, and the measured trade of recall for safety. Every number on screen or in the voice is read from the page or the results file at record time; script and method in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

Built for Graph Hacks (WeMakeDevs × FalkorDB). Primary track T1, Agents That Act on Connected Data; also T3, Company Brain, and T2, Agent Memory & Coordination.

---

## In short

Faultline answers four questions during an incident. Each answer comes out of a FalkorDB query, and the agent cannot skip one.

| Question | How it is decided |
|---|---|
| What breaks? | `algo.BFS` blast radius over failure-flow edges |
| Why? | `algo.SPpaths` must return a causal path from the change to the symptom, and `algo.maxFlow` must show the change can carry the observed impact |
| What is the smallest containment? | max-flow → min-cut on the failure graph, each candidate tried on its own `GRAPH.COPY` branch with a predicted outcome before anyone approves |
| Who should fix it? | `algo.HarmonicCentrality` over who touched the code, who resolved it before and who is on call; `algo.MSF` for escalation |

It then takes one human-approved action, verifies it through a second channel (APPLIED, NOT_APPLIED or UNKNOWN), and writes the decision back into the same graph, so the next incident starts warm. The same graph blocks risky PRs before they ship (preflight) and answers "who owns, knows and decided what" with cited node ids (company brain).

**Faultline trades recall for safety.** It will not blame a change until FalkorDB proves a causal path and enough capacity, so where a heuristic guesses, it abstains and hands the incident to a human. Measured on the deep bench: <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> generated worlds built to trap it (causes 1–4 hops upstream, look-alike deploys on the path and on the alerting service, five adversarial kinds), against two telemetry heuristics and a strong LLM given the same evidence. Square brackets hold 95 % intervals; `make claims` checks every number against [`evals/results/latest.json`](evals/results/latest.json):

| Same <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds | Right cause (of <!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim --> worlds that have one) | Confident wrong blames | Abstained (handed to a human) |
|---|---|---|---|
| **Faultline** | **<!-- claim:deep.fresh.all.right_cause -->51<!-- /claim -->** [<!-- claim:deep.fresh.all.right_cause.ci_lo -->41%<!-- /claim -->–<!-- claim:deep.fresh.all.right_cause.ci_hi -->61%<!-- /claim -->] | **<!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim -->** [0–<!-- claim:deep.fresh.all.wrong_confident.ci_hi -->2.7%<!-- /claim -->] | <!-- claim:deep.fresh.all.abstained -->89<!-- /claim --> |
| Telemetry only (blame the most anomalous changed component) | <!-- claim:deep.fresh.all.T.right_strict -->85<!-- /claim --> | <!-- claim:deep.fresh.all.T.wrong_any -->55<!-- /claim --> | <!-- claim:deep.fresh.all.T.abstained -->0<!-- /claim -->, it cannot |
| The same, allowed to say "none" (T+) | <!-- claim:deep.fresh.all.Tplus.right_strict -->85<!-- /claim --> | <!-- claim:deep.fresh.all.Tplus.wrong_any -->55<!-- /claim --> | <!-- claim:deep.fresh.all.Tplus.abstained -->0<!-- /claim --> |
| A strong LLM alone (`claude-opus-5-5`, the same telemetry and change list) | <!-- claim:llm_deep.deep.all.right_cause -->66<!-- /claim --> [<!-- claim:llm_deep.deep.all.right_cause.ci_lo -->56%<!-- /claim -->–<!-- claim:llm_deep.deep.all.right_cause.ci_hi -->75%<!-- /claim -->] | **<!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim -->** [<!-- claim:llm_deep.deep.all.wrong_confident.ci_lo -->20%<!-- /claim -->–<!-- claim:llm_deep.deep.all.wrong_confident.ci_hi -->34%<!-- /claim -->] | <!-- claim:llm_deep.deep.all.abstained -->37<!-- /claim --> |

On <!-- claim:seeds.deep.seeds -->3<!-- /claim --> more deep-bench seeds generated for the first time in this audit (<!-- claim:seeds.deep.cases -->420<!-- /claim --> worlds) the trade holds: right cause <!-- claim:seeds.deep.right_cause -->136<!-- /claim --> of <!-- claim:seeds.deep.cause_cases -->300<!-- /claim -->, confident wrong blames <!-- claim:seeds.deep.wrong_confident -->0<!-- /claim --> [0–<!-- claim:seeds.deep.wrong_confident.ci_hi -->0.9%<!-- /claim -->], against <!-- claim:seeds.deep.T.right_strict -->249<!-- /claim --> and <!-- claim:seeds.deep.T.wrong_any -->171<!-- /claim --> for telemetry only. On <!-- claim:seeds2.deep.seeds -->8<!-- /claim --> further pre-registered seeds (<!-- claim:seeds2.deep.cases -->1120<!-- /claim --> worlds) it held again: right cause <!-- claim:seeds2.deep.right_cause -->382<!-- /claim --> of <!-- claim:seeds2.deep.cause_cases -->800<!-- /claim -->, confident wrong blames <!-- claim:seeds2.deep.wrong_confident -->0<!-- /claim --> [0–<!-- claim:seeds2.deep.wrong_confident.ci_hi -->0.3%<!-- /claim -->], against <!-- claim:seeds2.deep.T.right_strict -->671<!-- /claim --> and <!-- claim:seeds2.deep.T.wrong_any -->449<!-- /claim --> for telemetry only. Not every abstention is clean: in <!-- claim:deep.fresh.accepted_nc.bystander -->9<!-- /claim --> of the headline worlds and <!-- claim:seeds.deep.accepted_nc.bystander -->24<!-- /claim --> of the new ones the gate ended "not confident" while naming an innocent change as its suspect ([Results](#results)).

- **On a real running system.** We injected the OpenTelemetry Demo's own fault flags into the running demo. Its services and span-metric telemetry are real; the topology and capacities (hand-encoded from its docs, unchanged since before the bench), the decoy changes and the page rule are ours. After a fix found on the first window (as registered: <!-- claim:otel.faultline_prefix.right_cause.k -->0<!-- /claim --> right, <!-- claim:otel.faultline_prefix.no_incident_fault -->15<!-- /claim --> real faults called "no incident"), Faultline named the right cause in <!-- claim:otel.faultline.right_cause.k -->11<!-- /claim --> of <!-- claim:otel.faultline.right_cause.n -->20<!-- /claim --> fault windows and blamed a wrong change <!-- claim:otel.faultline.wrong.k -->0<!-- /claim --> times in <!-- claim:otel.faultline.wrong.n -->40<!-- /claim --> windows; <!-- claim:otel.accepted_nc.bystander -->3<!-- /claim --> of its abstentions named an innocent change as a "not confident" suspect. Thresholded telemetry (T+) was right <!-- claim:otel.Tplus.right_cause.k -->13<!-- /claim --> times and wrong <!-- claim:otel.Tplus.wrong.k -->8<!-- /claim -->; recency was right <!-- claim:otel.N.right_cause.k -->17<!-- /claim --> times and wrong <!-- claim:otel.N.wrong.k -->23<!-- /claim -->. The graph did the rejecting: no causal path (G2) removed <!-- claim:otel.gate.decoys.G2 -->73<!-- /claim --> of the <!-- claim:otel.gate.decoys -->120<!-- /claim --> decoys, and <!-- claim:otel.gate.tplus_wrong_picks.G2 -->5<!-- /claim --> of T+'s <!-- claim:otel.gate.tplus_wrong_picks -->8<!-- /claim --> wrong picks; max flow (G5) removed <!-- claim:otel.gate.decoys.G5 -->0<!-- /claim --> here. [Details](docs/EVALS.md#faultbench-otel-a-real-system-real-telemetry-pre-registered-2026-10-16).
- **Where the graph decides alone.** When the look-alike is itself faulty, the origin check cannot reject it; only the graph can. On <!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> such worlds where the look-alike reaches the alert only through best-effort calls, the right cause is blamed in <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim -->; with `algo.maxFlow` removed, in <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim --> ([decisive bench](#results)).
- **FalkorDB switched off (arm A4):** the agent confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes. That is by design, not a measurement: every read goes through FalkorDB, so it fails closed.
- **Context for an agent**, with 30 unrelated deploys in the window: the true cause's rank (MRR, 1 = first) is <!-- claim:ctx.busy30.b1000.GA.mrr -->0.66<!-- /claim --> [<!-- claim:ctx.busy30.b1000.GA.mrr_ci_lo -->0.60<!-- /claim -->–<!-- claim:ctx.busy30.b1000.GA.mrr_ci_hi -->0.72<!-- /claim -->] in the graph's context pack, <!-- claim:ctx.busy30.b1000.TR.mrr -->0.56<!-- /claim --> when the same window's changes are ranked by telemetry alone, <!-- claim:ctx.busy30.b1000.V.mrr -->0.42<!-- /claim --> with vector RAG and <!-- claim:ctx.busy30.b1000.R.mrr -->0.08<!-- /claim --> by recency. On the same worlds, the graph's scoping adds <!-- claim:ctx.busy30.b1000.GA_minus_TR.mrr_diff -->0.10<!-- /claim --> [<!-- claim:ctx.busy30.b1000.GA_minus_TR.ci_lo -->0.06<!-- /claim -->–<!-- claim:ctx.busy30.b1000.GA_minus_TR.ci_hi -->0.14<!-- /claim -->] to telemetry alone. Graph distance on its own scores only <!-- claim:ctx.busy30.b1000.G.mrr -->0.39<!-- /claim -->.

The full scorecard (each number with its N, a 95 % interval and whether it is measured or true by design; baselines, adversarial and new-seed benches, mutation testing, crash and contention safety, scale, speed and the live deployment) is in **[docs/PROOF.md](docs/PROOF.md)**.

![Faultline trades recall for safety: right causes, confident wrong blames and abstentions on the deep bench, against telemetry-only heuristics, with 95 % intervals](docs/media/charts/deep.svg)

## Proof at a glance

Every result in one table. Each number is tagged and checked against [`evals/results/latest.json`](evals/results/latest.json) by `make claims`; each row links to its method and pre-registration. Intervals and the full scorecard: [docs/PROOF.md](docs/PROOF.md).

| Claim | Faultline | Compared with | Bench |
|---|---|---|---|
| It does not blame an innocent change | <!-- claim:seedsall.deep.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:seedsall.deep.cases -->1540<!-- /claim --> adversarial worlds on <!-- claim:seedsall.deep.seeds -->11<!-- /claim --> seeds [0–<!-- claim:seedsall.deep.wrong_confident.ci_hi -->0.25%<!-- /claim -->], and <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> in the <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> headline worlds | telemetry only: <!-- claim:seedsall.deep.T.wrong_any -->620<!-- /claim --> wrong in the same <!-- claim:seedsall.deep.cases -->1540<!-- /claim -->; a strong LLM alone: <!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim --> in the <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> | [deep bench](docs/EVALS.md#the-numbers-audit-2026-10-16-intervals-new-seeds-and-harder-comparisons) |
| The graph decides, not the model | right cause <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim -->/<!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> with `algo.maxFlow`, <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim -->/20 without it | a strong LLM alone on the same <!-- claim:llm_deep.decisive.g5_only.cases -->20<!-- /claim --> worlds: <!-- claim:llm_deep.decisive.g5_only.right_cause -->14<!-- /claim --> right, <!-- claim:llm_deep.decisive.g5_only.wrong_confident -->3<!-- /claim --> wrong | [decisive bench](docs/EVALS.md#the-numbers-audit-2026-10-16-intervals-new-seeds-and-harder-comparisons) |
| It holds on a real running system | on the OpenTelemetry Demo's real services and telemetry, broken with its own fault flags (topology, decoys and page rule ours), the right cause in <!-- claim:otel.faultline.right_cause.k -->11<!-- /claim -->/<!-- claim:otel.faultline.right_cause.n -->20<!-- /claim --> fault windows and <!-- claim:otel.faultline.wrong.k -->0<!-- /claim --> wrong blames in <!-- claim:otel.faultline.wrong.n -->40<!-- /claim --> windows [0–<!-- claim:otel.faultline.wrong.ci_hi -->8.8%<!-- /claim -->]; the rest abstained (<!-- claim:otel.accepted_nc.bystander -->3<!-- /claim --> naming an innocent "not confident" suspect); no causal path removed <!-- claim:otel.gate.decoys.G2 -->73<!-- /claim --> of <!-- claim:otel.gate.decoys -->120<!-- /claim --> decoys | thresholded telemetry (T+): <!-- claim:otel.Tplus.right_cause.k -->13<!-- /claim --> right, <!-- claim:otel.Tplus.wrong.k -->8<!-- /claim --> wrong; recency: <!-- claim:otel.N.right_cause.k -->17<!-- /claim --> right, <!-- claim:otel.N.wrong.k -->23<!-- /claim --> wrong | [FaultBench-OTel](docs/EVALS.md#faultbench-otel-a-real-system-real-telemetry-pre-registered-2026-10-16) |
| On call, end to end | <!-- claim:oncall.night.steps_passed -->14<!-- /claim -->/<!-- claim:oncall.night.steps -->14<!-- /claim --> steps: page, escalate, acknowledge, approve, verified APPLIED; the same fault again paged <!-- claim:oncall.night.inc2.people_woken -->0<!-- /claim --> people under a standing contract (only <!-- claim:oncall.night.inc2.notices -->5<!-- /claim --> silent information notices); the contract fired in <!-- claim:oncall.night.negatives_fired -->0<!-- /claim --> of <!-- claim:oncall.night.negatives -->5<!-- /claim --> cases outside its terms | the first time, by design: <!-- claim:oncall.night.inc1.people_woken -->5<!-- /claim --> people paged | [on-call night](#on-call-page-acknowledge-escalate-standing-approval) |
| It learns from the people who use it | the fix the on-call keeps choosing ranked first on both scenarios (<!-- claim:learn.choices.scenarios -->S1,S1b<!-- /claim -->; a deterministic check, three identical runs each); gate verdicts unchanged; T2 go/no-go <!-- claim:t2.green -->5<!-- /claim -->/<!-- claim:t2.items -->5<!-- /claim --> | cold: the rollback first on both | [learning night](#learns-from-the-people-who-use-it-t2) |
| The company brain on questions it never saw | <!-- claim:brain_blind.s2.hybrid.correct -->24<!-- /claim -->/<!-- claim:brain_blind.s2.hybrid.questions -->40<!-- /claim --> with FalkorDB vector + full-text routing | keyword routing alone <!-- claim:brain_blind.s2.keyword_router.correct -->19<!-- /claim -->/<!-- claim:brain_blind.s2.keyword_router.questions -->40<!-- /claim --> | [blind set](docs/EVALS.md#the-numbers-audit-2026-10-16-intervals-new-seeds-and-harder-comparisons) |
| The vector index, tuned on the engine | recall@10 <!-- claim:vector.recall_at_10.tuned -->1.0<!-- /claim --> on <!-- claim:vector.queries -->702<!-- /claim --> queries over <!-- claim:vector.sets -->9<!-- /claim --> sets (M 32, efConstruction 400, efRuntime 100) | the defaults: <!-- claim:vector.recall_at_10.default -->0.9767<!-- /claim --> on the hardest set (<!-- claim:vector.history2k_incident.queries -->60<!-- /claim --> queries over <!-- claim:vector.history2k_incident.vectors -->2040<!-- /claim --> vectors); the settings were chosen on these same queries | [vector recall](docs/GRAPH_MODEL.md#indexes-and-constraints) (`evals/vector_recall.py`) |
| The company brain against FalkorDB's own GraphRAG-SDK | on blind questions <!-- claim:graphrag.s2.fl.correct -->24<!-- /claim -->/<!-- claim:graphrag.s2.questions -->40<!-- /claim -->, p50 <!-- claim:graphrag.s2.fl.ms_p50 -->18.1<!-- /claim --> ms and no model call | **the SDK answered more:** <!-- claim:graphrag.s2.sdk.correct -->32<!-- /claim -->/<!-- claim:graphrag.s2.questions -->40<!-- /claim --> (paired p <!-- claim:graphrag.s2.paired.mcnemar_p -->0.12<!-- /claim -->), at <!-- claim:graphrag.s2.sdk.s_p50 -->3.09<!-- /claim --> s and $<!-- claim:graphrag.s2.sdk.usd_per_question -->0.009<!-- /claim --> a question | [GraphRAG-SDK arm](docs/EVALS.md#company-brain-vs-falkordbs-graphrag-sdk-pre-registered-2026-10-17) |
| FalkorDB at scale | <!-- claim:tenants.n -->250<!-- /claim --> tenant graphs on one engine with <!-- claim:tenants.acl.leaks -->0<!-- /claim --> leaks in <!-- claim:tenants.acl.cross.n -->1000<!-- /claim --> cross-tenant reads; at <!-- claim:scale.10k.services -->10000<!-- /claim --> services the proof path's engine p99 is <!-- claim:scale.10k.tail.Q-GATE-1.engine_ms_p99 -->8.926<!-- /claim --> ms; p99 <!-- claim:tenants.c64.p99_ms -->6.62<!-- /claim --> ms with 64 investigators in parallel | all 10 `algo.*` against NetworkX on the same graph: same answers on <!-- claim:algo10k.same -->9<!-- /claim --> of <!-- claim:algo10k.comparable -->11<!-- /claim -->, engine faster on <!-- claim:algo10k.faster_engine -->11<!-- /claim --> of <!-- claim:algo10k.timed_pairs -->12<!-- /claim --> | [Why FalkorDB, in numbers](#why-falkordb-in-numbers) |
| It cannot act twice | <!-- claim:contention.responders -->24<!-- /claim --> approvals of one plan at once: <!-- claim:contention.same.accepted -->1<!-- /claim --> accepted, <!-- claim:contention.same.prs -->1<!-- /claim --> PR; killed between execute and verify: exactly once; <!-- claim:mutation.killed -->41<!-- /claim -->/<!-- claim:mutation.mutants -->41<!-- /claim --> safety mutants caught | a retry without the idempotency key merged <!-- claim:chaos.control_merged_prs -->2<!-- /claim --> PRs | [safety](#safety) |
| It gives back to FalkorDB | a fix as a pull request to GraphRAG-SDK ([#345](https://github.com/FalkorDB/GraphRAG-SDK/pull/345)), so the SDK runs on the engine we pin; issues [#3349](https://github.com/FalkorDB/FalkorDB/issues/3349), [#3376](https://github.com/FalkorDB/FalkorDB/issues/3376) and [#3377](https://github.com/FalkorDB/FalkorDB/issues/3377); new evidence on [#3150](https://github.com/FalkorDB/FalkorDB/issues/3150#issuecomment-6201125566) (a server panic) and [#2502](https://github.com/FalkorDB/FalkorDB/issues/2502#issuecomment-6237945777); one finding reported privately | | [docs/upstream](docs/upstream/) |

## Why FalkorDB, in numbers

Measured on the pinned engine (FalkorDB 6.0.2), in the terms FalkorDB uses for itself: graphs per instance, p99 under concurrent clients, memory, algorithm speed. These are Faultline's own workloads on one laptop, not a comparison with another database. Methods were pre-registered ([evals/PREREGISTRATION.md](evals/PREREGISTRATION.md), M20 addendum); details in [docs/EVALS.md](docs/EVALS.md#engine-numbers-in-falkordbs-own-terms-m20-pre-registered-2026-10-17).

| FalkorDB's yardstick | Faultline, measured | Source |
|---|---|---|
| Many isolated graphs on one instance | **<!-- claim:tenants.n -->250<!-- /claim --> tenant graphs** on one engine (maxmemory <!-- claim:tenants.maxmemory_mb -->3500.0<!-- /claim --> MB, shared with the product's own graphs): <!-- claim:tenants.product.n -->50<!-- /claim --> full product tenants at <!-- claim:tenants.product.mb_per_tenant -->15.0<!-- /claim --> MB each, <!-- claim:tenants.small.n -->200<!-- /claim --> topology-only tenants at <!-- claim:tenants.small.mb_per_tenant -->3.0<!-- /claim --> MB; a new tenant is one `GRAPH.COPY` (p50 <!-- claim:tenants.product.copy_ms_p50 -->61.239<!-- /claim --> ms). **<!-- claim:tenants.acl.leaks -->0<!-- /claim --> leaks** in <!-- claim:tenants.acl.cross.n -->1000<!-- /claim --> cross-tenant reads by per-tenant ACL users (95 % upper bound on the leak rate <!-- claim:tenants.acl.leak.ci_hi -->0.0038<!-- /claim -->) | [`evals/tenants_bench.py`](evals/tenants_bench.py) |
| p99 under concurrent clients | <!-- claim:tenants.c64.qps -->21694.6<!-- /claim --> gate reads/s from 64 parallel investigators on random tenants, p99 **<!-- claim:tenants.c64.p99_ms -->6.62<!-- /claim --> ms**, <!-- claim:tenants.c64.errors -->0<!-- /claim --> errors; one investigator: p99 <!-- claim:tenants.c1.p99_ms -->1.4<!-- /claim --> ms. At 64 the Python clients, not the engine (<!-- claim:tenants.c64.engine_cpu_cores -->7.15<!-- /claim --> cores busy), set the ceiling | [`evals/tenants_bench.py`](evals/tenants_bench.py) |
| Fast enough for every agent step | at <!-- claim:scale.10k.services -->10000<!-- /claim --> services (<!-- claim:scale.10k.nodes -->296261<!-- /claim --> nodes, <!-- claim:scale.10k.edges -->1097675<!-- /claim --> edges), engine p99 over 200 runs: the G2 proof path (`algo.SPpaths`) **<!-- claim:scale.10k.tail.Q-GATE-1.engine_ms_p99 -->8.926<!-- /claim --> ms**, the G5 capacity bound (`algo.maxFlow`) <!-- claim:scale.10k.tail.Q-GATE-3.engine_ms_p99 -->22.261<!-- /claim --> ms, the blast radius (`algo.BFS`) <!-- claim:scale.10k.tail.Q-BLAST-1.engine_ms_p99 -->3.279<!-- /claim --> ms | [`evals/scale.py`](evals/scale.py) |
| Linear scalability | proof-path p99 at 1k / 3k / 5k / 10k services: <!-- claim:scale.1k.tail.Q-GATE-1.engine_ms_p99 -->0.852<!-- /claim --> / <!-- claim:scale.3k.tail.Q-GATE-1.engine_ms_p99 -->3.602<!-- /claim --> / <!-- claim:scale.5k.tail.Q-GATE-1.engine_ms_p99 -->4.031<!-- /claim --> / <!-- claim:scale.10k.tail.Q-GATE-1.engine_ms_p99 -->8.926<!-- /claim --> ms, the planted incident decided correctly at all <!-- claim:scale.sizes_run -->4<!-- /claim --> sizes | [`evals/scale.py`](evals/scale.py) |
| Memory | <!-- claim:scale.10k.bytes_per_elem -->369<!-- /claim --> bytes per node-or-edge at 10k services, properties and indexes included (<!-- claim:scale.10k.used_bytes_per_elem -->447<!-- /claim --> by the engine's `used_memory` growth); the same extracted graph takes <!-- claim:algo10k.mem.falkordb_mb -->86.7<!-- /claim --> MB in FalkorDB and <!-- claim:algo10k.mem.networkx_mb -->107.7<!-- /claim --> MB in NetworkX | [`evals/scale.py`](evals/scale.py), [`evals/algo10k.py`](evals/algo10k.py) |
| Algorithm speed | all 10 `algo.*` at 10k services against NetworkX on the same input: same answers on <!-- claim:algo10k.same -->9<!-- /claim --> of <!-- claim:algo10k.comparable -->11<!-- /claim --> comparable workloads (PageRank's 10th place and the approximate harmonic centrality differ); engine time faster on <!-- claim:algo10k.faster_engine -->11<!-- /claim --> of <!-- claim:algo10k.timed_pairs -->12<!-- /claim -->, e.g. exact betweenness <!-- claim:algo10k.betweenness.falkor_ms_p50 -->255.217<!-- /claim --> ms against <!-- claim:algo10k.betweenness.nx_ms_p50 -->54707.892<!-- /claim --> ms, max flow <!-- claim:algo10k.maxflow.single.falkor_ms_p50 -->8.592<!-- /claim --> ms against <!-- claim:algo10k.maxflow.single.nx_ms_p50 -->163.826<!-- /claim --> ms. Client wall time faster on only <!-- claim:algo10k.faster_wall -->5<!-- /claim -->: parsing a whole-graph result in Python costs more than computing it | [`evals/algo10k.py`](evals/algo10k.py) |
| Real time | a written alert is visible to the next read-only decision query in p50 <!-- claim:perf.fresh.alert.p50_ms -->0.727<!-- /claim --> ms (<!-- claim:perf.fresh.alert.first_read_saw_it -->50<!-- /claim -->/<!-- claim:perf.fresh.alert.writes -->50<!-- /claim --> on the first read) | [`evals/perf_vs_flat.py`](evals/perf_vs_flat.py) |

## What the judges asked for

The rules and the organiser's day-1 post ("How to Build an Agent That Reasons Over a Graph", section "What Judges Are Looking For") name what is judged. Each line below is quoted, then answered with a measured number:

| Judging line | What Faultline does | Evidence |
|---|---|---|
| "The graph has to shape what the agent does, not sit on the side" (challenge text); "whether the graph is doing work the agent could not do without it" (organiser post) | every verdict is a read-only FalkorDB query, and taking one algorithm away changes decisions | when the look-alike is itself faulty, the right cause in <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim -->/<!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> worlds with `algo.maxFlow`, <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim --> without it ([decisive bench](docs/EVALS.md)); without both `algo.SPpaths` and `algo.maxFlow`, <!-- claim:ladder.full.b.right_cause -->65<!-- /claim --> → <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim --> of <!-- claim:ladder.neither.b.confirm_cases -->65<!-- /claim --> ([ladder](#the-graph-is-load-bearing)); one perturbation test per algorithm use in [`test_algo_load_bearing.py`](tests/live/test_algo_load_bearing.py) |
| "If the product still works once FalkorDB is taken out, the graph is decoration" (rule R3) | with FalkorDB off (arm A4) the run cannot start, and the UI says so | confirmed causes <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim -->. That is by design, not a measurement: the product fails closed instead of degrading |
| "Run the same question twice", "with a depth of one", then "with a depth of four" (organiser post) | the proof path is `algo.SPpaths` over up to 8 hops of change → gate → failure-flow edges; the deep bench plants causes 1 to 4 hops upstream of the alert | right cause / worlds with a cause at 1 hop <!-- claim:deep.fresh.hops.1.right_cause -->16<!-- /claim -->/<!-- claim:deep.fresh.hops.1.cause_cases -->28<!-- /claim -->, 2 hops <!-- claim:deep.fresh.hops.2.right_cause -->18<!-- /claim -->/<!-- claim:deep.fresh.hops.2.cause_cases -->37<!-- /claim -->, 3 hops <!-- claim:deep.fresh.hops.3.right_cause -->4<!-- /claim -->/<!-- claim:deep.fresh.hops.3.cause_cases -->13<!-- /claim -->, 4 hops <!-- claim:deep.fresh.hops.4.right_cause -->0<!-- /claim -->/<!-- claim:deep.fresh.hops.4.cause_cases -->2<!-- /claim -->, plus <!-- claim:deep.fresh.nohops.right_cause -->13<!-- /claim -->/<!-- claim:deep.fresh.nohops.cause_cases -->20<!-- /claim --> weak-link worlds with no hop count; confident wrong blames <!-- claim:deep.fresh.hops.1.wrong_confident -->0<!-- /claim -->, <!-- claim:deep.fresh.hops.2.wrong_confident -->0<!-- /claim -->, <!-- claim:deep.fresh.hops.3.wrong_confident -->0<!-- /claim -->, <!-- claim:deep.fresh.hops.4.wrong_confident -->0<!-- /claim -->. Depth costs recall (deep causes are mostly handed to a human), never a wrong blame |
| "Ask the agent something that is not in the graph and let it say so" (organiser post) | the brain says "not in the graph" and cites nothing; the gate ends with NO_INCIDENT or abstains instead of guessing | brain: <!-- claim:brain.unanswerable_honest -->6<!-- /claim -->/<!-- claim:brain.unanswerable -->6<!-- /claim --> unanswerable questions answered honestly with no citations; deep bench: in <!-- claim:deep.fresh.abstain_downstream.correct -->20<!-- /claim -->/<!-- claim:deep.fresh.abstain_downstream.cases -->20<!-- /claim --> worlds where no change explains the alert, no change blamed; correct abstention on the control and no-cause scenarios: <!-- claim:arm.A3.abstention_correct_rate -->1.0<!-- /claim --> |
| "An empty traversal means your graph does not know about a dependency, which during an incident is a different and more worrying statement than safety" (organiser post) | G2 is "no path → no claim", never "no path → safe": when the graph lacks a link the gate abstains and hands over | one failure link hidden on the cause's path: <!-- claim:learning.i1_abstained -->22<!-- /claim -->/<!-- claim:learning.cases -->24<!-- /claim --> abstained, <!-- claim:learning.i1_wrong_confident -->0<!-- /claim --> wrong-confident ([learning eval](docs/EVALS.md)); one random real edge missing from the graph: <!-- claim:mismatch.hidden.wrong_confident -->0<!-- /claim --> wrong-confident in <!-- claim:mismatch.hidden.cases -->100<!-- /claim --> (<!-- claim:mismatch.hidden.abstained -->21<!-- /claim --> abstained), against <!-- claim:mismatch.arm_t.wrong_blame -->27<!-- /claim --> wrong blames for telemetry alone; telemetry missing for a fifth of components: <!-- claim:robustness.missing.0.2.wrong_confident -->0<!-- /claim --> wrong-confident, <!-- claim:robustness.missing.0.2.abstained -->37<!-- /claim --> abstained |
| "One instance can hold thousands of isolated graphs, so each user, agent, or tenant gets its own" (about the sponsor) | one graph per tenant with its own read-only ACL user; a tenant is a `GRAPH.COPY` | <!-- claim:tenants.n -->250<!-- /claim --> tenant graphs on one engine, <!-- claim:tenants.acl.leaks -->0<!-- /claim --> leaks in <!-- claim:tenants.acl.cross.n -->1000<!-- /claim --> cross-tenant reads (95 % upper bound <!-- claim:tenants.acl.leak.ci_hi -->0.0038<!-- /claim -->); p99 <!-- claim:tenants.c64.p99_ms -->6.62<!-- /claim --> ms with 64 investigators in parallel, <!-- claim:tenants.c64.errors -->0<!-- /claim --> errors |
| "Traversals are fast enough to run on every step of an agent loop" (about the sponsor) | the gate runs its path, capacity and blast reads on every incident | at <!-- claim:scale.10k.services -->10000<!-- /claim --> services, engine p99: `algo.SPpaths` <!-- claim:scale.10k.tail.Q-GATE-1.engine_ms_p99 -->8.926<!-- /claim --> ms, `algo.maxFlow` <!-- claim:scale.10k.tail.Q-GATE-3.engine_ms_p99 -->22.261<!-- /claim --> ms, `algo.BFS` <!-- claim:scale.10k.tail.Q-BLAST-1.engine_ms_p99 -->3.279<!-- /claim --> ms |

## Contents

- [Proof at a glance](#proof-at-a-glance)
- [Why FalkorDB, in numbers](#why-falkordb-in-numbers)
- [What the judges asked for](#what-the-judges-asked-for)
- [Reproduce it](#reproduce-it)
- [Why existing approaches fall short](#why-existing-approaches-fall-short)
- [How one incident flows](#how-one-incident-flows)
- [See it work: two incidents](#see-it-work-two-incidents)
- [The evidence gate](#the-evidence-gate)
- [Architecture](#architecture)
- [Graph model](#graph-model)
- [FalkorDB feature map](#falkordb-feature-map)
- [The graph is load-bearing](#the-graph-is-load-bearing)
- [Results](#results) (scorecard: [docs/PROOF.md](docs/PROOF.md))
- [What makes it different](#what-makes-it-different)
- [Context for any agent](#context-for-any-agent)
- [Memory, company brain, preflight, coordination](#memory-company-brain-preflight-coordination)
- [On-call: page, acknowledge, escalate, standing approval](#on-call-page-acknowledge-escalate-standing-approval)
- [Learns from the people who use it (T2)](#learns-from-the-people-who-use-it-t2)
- [Screens](#screens)
- [Query catalogue](#query-catalogue)
- [Safety](#safety)
- [What's real vs synthetic](#whats-real-vs-synthetic)
- [Honest limits](#honest-limits)
- [What didn't work](#what-didnt-work)
- [Existing system and what was built here](#existing-system-and-what-was-built-here)
- [AI disclosure](#ai-disclosure)

## Reproduce it

One command checks everything offline. It needs Docker, `uv` and Node. There is no API key, no GitHub token and nothing remote.

```bash
git clone https://github.com/Prashant-thakur77/Faultline.git && cd Faultline
make setup && make judge-check     # several minutes; prints PASS
```

`judge-check` starts the pinned FalkorDB, runs the engine smoke suite, seeds both tenants, runs the unit and live tests (isolation and concurrency included), checks the pipeline invariants, runs the lints and the claims check, and builds the frontend. CI runs the same steps on the pinned engine ([`ci.yml`](.github/workflows/ci.yml)). A `.devcontainer/` is included for a Codespace.

To run the product:

```bash
make up             # pinned FalkorDB (deploy/docker-compose.yml)
make seed           # acme + golden copies (TENANT=globex for the second tenant)
make demo           # API :8400 + UI :3000 → run S1, choose and approve an option, watch VERIFY → RESOLVED
make mcp            # the agent's read-only graph tools over MCP (stdio)
make eval           # keyless eval arms → evals/RESULTS.md
```

**Sixty seconds, no build.** After `make up && make seed`, ask FalkorDB directly. `algo.SPpaths` returns the path a blame needs, and `algo.maxFlow` shows that a look-alike change cannot carry the impact (`email` → `checkout`: 0.02, the seeded edge cap of a best-effort call): <!-- noclaim: the seeded best-effort edge cap -->

```bash
docker exec -it faultline-falkordb redis-cli GRAPH.RO_QUERY tenant_acme "MATCH (c:Node {id:'payment'}), (s:Node {id:'checkout'}) CALL algo.SPpaths({sourceNode: c, targetNode: s, relTypes: ['PROPAGATES_TO'], weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 1}) YIELD path RETURN [n IN nodes(path) | n.id]"
docker exec -it faultline-falkordb redis-cli GRAPH.RO_QUERY tenant_acme "MATCH (e:Node {id:'email'}), (t:Node {id:'checkout'}) CALL algo.maxFlow({sourceNodes: [e], targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow RETURN maxFlow"
```

The first returns `[payment, checkout]`. With `targetNode` `kpi.exec_revenue` the same call crosses domains: `[payment, raw.raw_orders, staging.stg_orders, marts.fct_revenue, marts.exec_revenue_metric, kpi.exec_revenue]`. The second returns `0.02`; from `payment` it returns `1.0`. Scenario changes such as `D-pay-417` exist only inside a scenario's clean room. On the seeded tenant the history is there to query, for example `MATCH (d:Deploy)-[:CAUSED]->(i:Incident) RETURN d.id, i.id LIMIT 5`.

**Break it yourself.** `make demo`, then open **Break it** (`/playground`). Pick one change: remove the proof-path call, make a call best-effort, make the decoy's call critical, cut a service off, or have the top responder leave. It is applied to a `GRAPH.COPY` of the hero incident, the product runs on both copies, and every decision is shown before and after with the Cypher that decides it.

**Replay without a backend.** The static replay site plays [`examples/s1-hero/`](examples/s1-hero) end to end: gate, containment, APPLIED, write-back verified <!-- claim:s1.writeback -->7/7<!-- /claim -->. Locally: `cd frontend && npm run build:pages`, then serve `out-pages/` under `/Faultline/`.

**Where each judging question is answered:**

| You are checking… | Look here |
|---|---|
| Is FalkorDB load-bearing, or decoration? | [the evidence gate](#the-evidence-gate) · [every algorithm perturbed, the decision flips](#the-graph-is-load-bearing) · the Break it page · arm A4 (FalkorDB off: confirms nothing) |
| How deep is the FalkorDB use? | [feature map](#falkordb-feature-map): <!-- claim:repo.algorithms -->10<!-- /claim --> `algo.*` procedures, `GRAPH.COPY` branches, vectors, full-text, FLEX UDFs, per-tenant ACL users, versioned topology · [query catalogue](docs/QUERY_CATALOGUE.md) |
| Does the agent act, safely? | two-step approval bound to a plan hash, three-valued verification, kill -9 chaos, write-back re-read: [Safety](#safety) · [`examples/s1-hero/`](examples/s1-hero/) |
| Does it learn? | a verified fix teaches the graph a missing link, and the next incident is proved: [Results](#results) · [docs/EVALS.md](docs/EVALS.md) |
| Are the numbers honest? | pre-registration, new never-generated seeds, 95 % intervals with N, structural zeros labelled, a wrong-graph eval, telemetry baselines that win on some worlds, mutants: [Results](#results) · [What didn't work](#what-didnt-work) · [docs/HONEST_LIMITS.md](docs/HONEST_LIMITS.md) |
| Company brain (T3)? | as-of answers with node-id citations, forget receipts: [Memory, company brain, preflight, coordination](#memory-company-brain-preflight-coordination) |

**Files to read first:**

| File | Why |
|---|---|
| [`graph/templates/gate_path.cypher`](backend/faultline/graph/templates/gate_path.cypher) | the proof path (G2) |
| [`agent/gate.py`](backend/faultline/agent/gate.py) | Gate v2, G1–G8, the competitor sweep |
| [`graph/ro.py`](backend/faultline/graph/ro.py) | the only read path |
| [`actions/act.py`](backend/faultline/actions/act.py) | approval → execute → three-valued verify → write-back |
| [`docs/QUERY_CATALOGUE.md`](docs/QUERY_CATALOGUE.md) | every query the product runs |

Deeper docs: [architecture](docs/ARCHITECTURE.md) (one incident end to end, with files) · [graph model](docs/GRAPH_MODEL.md) · [design decisions](docs/DESIGN_DECISIONS.md) · [evals in detail](docs/EVALS.md) · [explainer](docs/EXPLAINER.md) (the questions a judge asks) · [honest limits](docs/HONEST_LIMITS.md).

## Why existing approaches fall short

> How twelve current products approach root cause (Dynatrace, Datadog, New Relic, PagerDuty, BigPanda, Splunk ITSI, incident.io, Rootly, Causely, HolmesGPT, k8sgpt), from their public documentation, with sources, and where Faultline differs and where they are ahead: **[docs/LANDSCAPE.md](docs/LANDSCAPE.md)**.

Google's SRE book says "roughly 70% of outages are due to changes in a live system" ([SRE book, Introduction](https://sre.google/sre-book/introduction/)). Uptime Institute's 2025 outage analysis puts IT and networking at 23% of impactful outages and ties the rise to change management and misconfiguration ([press release](https://uptimeinstitute.com/about-ui/press-releases/uptime-announces-annual-outage-analysis-report-2025)); 54% of respondents said their latest significant outage cost more than $100,000 (as reported by [Data Center Knowledge](https://www.datacenterknowledge.com/outages/data-center-outages-decline-for-fourth-straight-year-but-issues-persist)). So the on-call question is usually "which change?", and a wrong answer rolls back the wrong thing. <!-- noclaim: external figures, quoted with their sources -->

There are three common ways to answer it today. Each is good at something, and each misses something an on-call engineer needs. We built a baseline for each one and measured it on the same scenarios as the product.

| Approach | What it does well | What it cannot do | Measured here |
|---|---|---|---|
| **Alert correlation and recency** ("what changed last, near the alert?") | fast, needs no model, groups alerts by time and labels | two changes in the same minute tie; it cannot tell a cause from a victim; it never says "no change explains this" | naive recency (arm N): top-1 <!-- claim:arm.N.top1 -->0.1<!-- /claim -->, false blame <!-- claim:arm.N.false_blame_rate -->1.0<!-- /claim -->, correct abstention <!-- claim:arm.N.abstention_correct_rate -->0.0<!-- /claim -->. A sharper telemetry-only heuristic (arm T) reaches top-1 <!-- claim:arm.T.top1 -->0.9<!-- /claim --> but still blames <!-- claim:arm.T.false_blame_rate -->0.2<!-- /claim --> of the time, and by design it cannot say "nothing explains this", so it blames a change in all <!-- claim:deep.fresh.abstain_downstream.cases -->20<!-- /claim --> deep-bench worlds where the right answer is to blame nothing |
| **LLM agent with vector RAG** over logs, tickets and runbooks | reads text well; finds incidents that look similar | similarity is not causation: two descriptive deploy titles score alike; nothing checks that a candidate can carry the impact; it answers instead of abstaining, and a look-alike change on the path reads like the cause; its memory is a pile of chunks, with no "who owns this now" | vector ranking (arm V, cosine in FalkorDB): top-1 <!-- claim:arm.V.top1 -->0.4<!-- /claim -->, false blame <!-- claim:arm.V.false_blame_rate -->0.6<!-- /claim -->, correct abstention <!-- claim:arm.V.abstention_correct_rate -->0.0<!-- /claim -->. As agent context with 30 unrelated deploys: MRR <!-- claim:ctx.busy30.b1000.V.mrr -->0.4226<!-- /claim -->. A strong LLM (`claude-opus-5-5`) given the same telemetry: <!-- claim:arm.A0.outcome_correct.k -->23<!-- /claim -->/<!-- claim:arm.A0.outcome_correct.n -->24<!-- /claim --> right on our 8 scenarios, but on <!-- claim:llm_deep.deep.all.cases -->140<!-- /claim --> adversarial worlds it confidently blames an innocent change in <!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim --> (Faultline: 0) ([Results](#results)) |
| **Static dependency maps and service catalogs** | list edges and owners | an edge says two things connect, not how much failure can cross it; maps drift out of date; no validity windows, decisions or past fixes attached; usually read by people, not checked at decision time | the capability ladder: with the path check reduced to plain connectivity and `algo.maxFlow` removed, the right cause is blamed in <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim -->/<!-- claim:ladder.neither.b.confirm_cases -->65<!-- /claim --> generated worlds, against <!-- claim:ladder.full.b.right_cause -->65<!-- /claim -->/<!-- claim:ladder.full.b.confirm_cases -->65<!-- /claim --> for the product |
| **Faultline**: graph proof, capacity bound, abstention | a causal path (`algo.SPpaths`), a max-flow bound on what a suspect can carry (`algo.maxFlow`), and eight read-only checks before any claim; it abstains when nothing passes; acts once, verifies, and writes back to the same graph | it needs a modelled failure-flow layer and telemetry on the components (see [Honest limits](#honest-limits)) | arm A3: top-1 <!-- claim:arm.A3.top1 -->1.0<!-- /claim -->, false blame <!-- claim:arm.A3.false_blame_rate -->0.0<!-- /claim -->, correct abstention <!-- claim:arm.A3.abstention_correct_rate -->1.0<!-- /claim -->; deep bench <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds; context MRR <!-- claim:ctx.busy30.b1000.GA.mrr -->0.6598<!-- /claim --> |

Five gaps run through current practice, and each one maps to a part of Faultline you can check:

| Gap | What Faultline does | Where to check |
|---|---|---|
| Similarity stands in for causation | G2 requires a directed causal path from the change to every symptom | [`gate_path.cypher`](backend/faultline/graph/templates/gate_path.cypher); `D-rec-12` rejected by <!-- claim:s1.D-rec-12.rejected_by -->G2<!-- /claim --> |
| Nothing proves the cause can carry the impact | G5 bounds the share of the symptom a suspect can explain with joint `algo.maxFlow` | [`gate_flow.cypher`](backend/faultline/graph/templates/gate_flow.cypher); gate bench G5 cases <!-- claim:gate_bench.G5.correct -->20<!-- /claim -->/<!-- claim:gate_bench.G5.cases -->20<!-- /claim --> (those look-alikes are healthy, so the origin check would reject them too; G5 decides alone on S2 and on the decisive bench) |
| Tools always name something | a three-valued outcome (confirmed, not confident, no incident) with a negative proof (`algo.SSpaths`) | gate bench abstention cases <!-- claim:gate_bench.abstain.correct -->20<!-- /claim -->/<!-- claim:gate_bench.abstain.cases -->20<!-- /claim --> by outcome (in <!-- claim:gate_bench.bystander_not_confident -->4<!-- /claim --> of them the gate accepted a bystander change as "not confident"), controls <!-- claim:gate_bench.control.correct -->15<!-- /claim -->/<!-- claim:gate_bench.control.cases -->15<!-- /claim --> |
| Actions are reported, not verified | a second channel decides APPLIED, NOT_APPLIED or UNKNOWN; UNKNOWN never writes success | S5 → <!-- claim:s5.verdict -->NOT_APPLIED<!-- /claim -->, S9 → <!-- claim:s9.verdict -->UNKNOWN<!-- /claim -->, success written: <!-- claim:s9.success_written -->False<!-- /claim --> |
| Memory is a vector store beside the system | incidents, fixes, decisions and runbooks are nodes in the same graph the gate reads; a verified fix can teach a missing link | next incidents correct after learning: <!-- claim:learning.i2_learned_correct -->24<!-- /claim -->/<!-- claim:learning.cases -->24<!-- /claim --> vs <!-- claim:learning.i2_control_correct -->2<!-- /claim --> without |

## How one incident flows

The hero scenario S1: checkout and frontend error rates jump. Three changes landed in the window, two of them in the same minute. Every step below is recorded in the graph as `StageEvent`, `ToolCall`, `Evidence` and `GateRun` nodes. Paths are relative to `backend/faultline/`.

| # | Step | What happens | FalkorDB query or procedure | File |
|---|---|---|---|---|
| 1 | Alert | The alerts that fired around onset become the symptoms; the incident is opened and its text embedded | `Q-ALERT-1`; `vecf32` on `Incident.embedding` | `graph/templates/window_alerts.cypher`, `scenario.py` |
| 2 | Recall | Similar past incidents, kept only if they share a `Symptom` node | `db.idx.vector.queryNodes` + structural confirm (`Q-MEM-1`) | `graph/templates/recall.cypher` |
| 3 | Scope | What is upstream of the symptoms, and what breaks downstream | `algo.SSpaths`, `algo.BFS`, `algo.betweenness` | `upstream_scope.cypher`, `blast_radius.cypher`, `chokepoints.cypher` |
| 4 | Suspects | The changes in the window, ranked for investigation order | `algo.SSpaths` (`Q-SUS-1`), `algo.pageRank` on a scratch projection | `upstream_suspects.cypher`, `rank_causes.cypher`, `agent/score.py` |
| 5 | Path | `D-rec-12` has no path to checkout: rejected | `algo.SPpaths` (`Q-GATE-1`) | `gate_path.cypher` |
| 6 | Flow | `D-email-88` has a path, but its max flow <!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim --> is below the <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> needed: rejected | joint `algo.maxFlow` × path multiplicity (`Q-GATE-3`, `Q-GATE-MULT`) | `gate_flow.cypher`, `gate_multiplicity.cypher` |
| 7 | Proof | `D-pay-417` passes G1–G7; G8 attaches the ADR-012 and ADR-013 it contradicts; one `GateRun` per verdict | eight read-only checks | `agent/gate.py`, `decision_contradiction.cypher` |
| 8 | Cut | Is a cut needed, what is the smallest one, and what happens under each option | `algo.WCC`; `algo.maxFlow` with `edgeFlows` → min-cut in code; one `GRAPH.COPY` branch per candidate (`Q-FUTURE-1`) | `connectivity.cypher`, `cut_flow.cypher`, `graph/algo/maxflow.py`, `futures.cypher` |
| 9 | Route | Who fixes it, who is looped in, who to notify | `algo.HarmonicCentrality`, `algo.MSF` on scratch projections | `harmonic.cypher`, `msf.cypher`, `mcp_server/tools.py` |
| 10 | Approve | Choosing an option renders the exact action and its plan hash; approval must quote the hash and moves the incident to EXECUTE in the same query | single-query writes `W_CHOOSE`, `W_APPROVE` | `actions/act.py`, `graph/writes.py` |
| 11 | Act and verify | A PR flips the `paymentGate` flag; GitHub main is re-read and telemetry is checked for every symptom → APPLIED | intent → execute → reconcile, idempotency key under a unique constraint | `actions/act.py`, `actions/github.py`, `actions/reconcile.py` |
| 12 | Write-back | `CAUSED`, `RESOLVED_BY`, a postmortem, a decision and `PRECEDENT_FOR` in one query, re-read through a separate read-only connection | `W_WB_1` + `writeback_check.cypher` | `graph/writes.py`; verified <!-- claim:s1.writeback -->7/7<!-- /claim --> |
| 13 | Warm recall | The incident joins a family; a derived runbook is consolidated; the repeat incident S1b starts warm | `algo.labelPropagation` | `families.cypher`, `memory/learn.py` |

On S1b (a repeat payment regression after S1 was resolved), the warm run's top precedent is S1 (<!-- claim:memory.warm_top_precedent_is_s1 -->True<!-- /claim -->), the derived runbook comes first (<!-- claim:memory.derived_runbook_first -->True<!-- /claim -->), the family prior rises from <!-- claim:memory.cold_prior -->0.7681<!-- /claim --> to <!-- claim:memory.warm_prior -->0.8423<!-- /claim -->, and the gate verdicts stay identical check by check (<!-- claim:memory.gate_verdicts_identical -->True<!-- /claim -->). Memory reorders; it never decides.

The full walk-through, with every function name, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## See it work: two incidents

Recorded through the real API (`scripts/record_demo.py`) with the deterministic investigator and simulated GitHub, both labelled as such everywhere.

| | **S1 service incident** (hero) | **S2 data incident** (cross-domain) |
|---|---|---|
| Symptom | checkout + frontend error rate | the executive revenue KPI jumps |
| Changes in the window | `D-pay-417` (payment), `D-email-88` (email, **same minute**), `D-rec-12` (recommendation) | `D-cutover-1` (payment provider cutover), `D-fx-pause-7` (FX feed paused) |
| Proof path (G2, `algo.SPpaths`) | <!-- claim:s1.chain -->D-pay-417 → payment → checkout<!-- /claim --> | <!-- claim:s2.chain -->D-cutover-1 → payment → raw.raw_orders → staging.stg_orders → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_revenue<!-- /claim --> |
| Look-alike rejected by **max flow** (G5) | `D-email-88`: max flow <!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim --> < needed <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> (the email call is best-effort: one modelled edge cap, [cited from the OTel demo source](data/topology/otel-demo.yaml)) | `D-fx-pause-7`: max flow <!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> < needed <!-- claim:s2.D-fx-pause-7.needed -->0.8<!-- /claim --> (FX touches a small share of revenue) |
| Rejected by **no path** (G2) | `D-rec-12` (<!-- claim:s1.D-rec-12.rejected_by -->G2<!-- /claim -->) | n/a |
| Decision contradiction (G8) | ADR-012 (timeout ≤ 2000 ms), ADR-013 (≥ 2 retries) | n/a |
| Containment | min-cut `payment → checkout` → flag `paymentGate` off (checkout defers the charge), or roll the deploy back (listed first: it worked more often on past incidents with this symptom) | min-cut found, but its only flag cuts a service edge no failure path to the KPI crosses, so it is shown disabled with that reason (`Q-LEVER-PATH`); the data repair needs a proposed transform patch (live LLM mode) |
| Who fixes it | ranked people with reasons (recent commits, past resolutions, on-call) | same |
| Action → verdict | PR to the infra repo (**simulated GitHub** here; the same path against real GitHub: [PR #1](https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1)) → **APPLIED**: main re-read + telemetry back in band, no collateral | awaiting a human choice |
| Write-back | verified <!-- claim:s1.writeback -->7/7<!-- /claim --> through a separate read-only connection, then LEARN | n/a |

Where naive recency and vector similarity put the real cause on every scenario, and why the look-alikes lost, is generated per run in [docs/NAIVE_VS_FAULTLINE.md](docs/NAIVE_VS_FAULTLINE.md).

## The evidence gate

Gate G2 is the load-bearing query. If it returns no rows, Faultline cannot claim the cause, whatever the model thinks:


```cypher
// Q-GATE-1, as rendered (gate_path.cypher writes {algo:sppaths}; graph/algo/registry.py resolves it on the pinned engine)
MATCH (c:Node {id:$cause}), (s:Node {id:$symptom})
CALL algo.SPpaths({sourceNode: c, targetNode: s, relTypes: ['CHANGED','GATES','PROPAGATES_TO'],
                   weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 3}) YIELD path, pathWeight
RETURN [n IN nodes(path) | n.id] AS chain, [r IN relationships(path) | type(r)] AS rels, pathWeight AS weight, length(path) AS hops
ORDER BY weight, hops LIMIT 3
```

What it returned on the eval run:


| Call | Rows |
|---|---|
| `D-pay-417` → checkout (S1, the real cause) | chain <!-- claim:s1.chain -->D-pay-417 → payment → checkout<!-- /claim --> |
| `D-rec-12` → checkout (S1, decoy) | **0 rows**: rejected by <!-- claim:s1.D-rec-12.rejected_by -->G2<!-- /claim --> ("no path, no claim") |
| `D-cutover-1` → kpi.exec_revenue (S2, data incident) | chain <!-- claim:s2.chain -->D-cutover-1 → payment → raw.raw_orders → staging.stg_orders → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_revenue<!-- /claim --> |

<details><summary>Show the other checks, their Cypher and how a verdict is reached</summary>


A path is necessary but not sufficient. G5 asks whether the change can carry the observed impact, as `algo.maxFlow` over `PROPAGATES_TO.cap`. On service edges `cap` is criticality; on lineage edges it is the end-to-end row share computed from the warehouse. The strongest case is S2: `D-fx-pause-7` has a multi-hop path to the revenue KPI, but it can carry at most <!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> of the anomaly, and <!-- claim:s2.D-fx-pause-7.needed -->0.8<!-- /claim --> is needed. Why the bound is valid, including the path-multiplicity factor and joint sufficiency for two causes, is in [docs/EXPLAINER.md](docs/EXPLAINER.md).

The model may propose; Gate v2 decides with eight checks, two of them split into a strict and a confidence part. Each is a read-only query ([`agent/gate.py`](backend/faultline/agent/gate.py)):

| Check | Query | Fails → |
|---|---|---|
| G1 grounded: the cause came back from a graph query this run, and every cited evidence item came from this run | Q-GATE-G1 | rejected |
| G2 path: `algo.SPpaths` from the change to every primary symptom | Q-GATE-1 | rejected ("no path, no claim") |
| G3 time: the change is inside the window before onset | Q-GATE-2 | rejected (an earlier upstream change → not confident) |
| G4 quantitative: an anomalous measurement on a node of the chain | Q-GATE-4 | rejected |
| G4 origin: the anomaly shows at the changed component itself or in its own data output (unless the change is on the alerting component) | Q-GATE-4 | not confident |
| G4 upstream (sweep): a suspect whose component is anomalous only by what an anomalous component upstream (changed or not) can carry there (measured excess × path transfer) is not the origin | Q-GATE-UPSTREAM | eliminated (an unchanged upstream origin → abstain) |
| G5 sufficiency: joint `algo.maxFlow` × the number of failure paths can carry the observed impact | Q-GATE-3, Q-GATE-MULT, Q-GATE-OBS | rejected (only jointly sufficient → not confident) |
| G6 competitors: every rival eliminated with evidence | Q-HYP-1 | unresolved rivals → not confident |
| G7 agreement: independent evidence channels agree on the chain | Q-GATE-7 | not confident |
| G7 correlation: the change specialist and the code or data specialist name the same deploy, which CHANGED a node of the chain | Q-GATE-CORR | not confident (not evaluable when no code/data channel could inspect a change) |
| G8 contradiction: active decisions the cause violates | Q-DEC-1 | attached, never blocks |

How a verdict is reached:

```mermaid
sequenceDiagram
  autonumber
  participant I as Lead investigator (policy or LLM)
  participant G as Gatekeeper (agent/gate.py, code)
  participant R as RO wrapper (graph/ro.py)
  participant F as FalkorDB tenant graph
  participant W as Writes (graph/writes.py)
  I->>G: confirm_root_cause(D-pay-417, evidence ids)
  G->>R: sweep every change in the window
  R->>F: GRAPH.RO_QUERY Q-GATE-1 (algo.SPpaths) per suspect
  F-->>R: D-rec-12 returns 0 rows
  G->>W: GateRun D-rec-12 rejected by G2
  R->>F: GRAPH.RO_QUERY Q-GATE-3 (algo.maxFlow) per surviving suspect
  F-->>R: D-email-88: flow below the observed share
  G->>W: GateRun D-email-88 rejected by G5
  G->>R: G1 grounding, G3 time, G4 origin and upstream, G6 rivals, G7 agreement
  R->>F: read-only templates, each with TIMEOUT and LIMIT
  F-->>R: all pass for D-pay-417
  G->>R: G8 decision contradictions (Q-DEC-1)
  F-->>G: ADR-012, ADR-013 (attached, never blocking)
  G->>W: GateRun D-pay-417 CONFIRMED
  G-->>I: verdict (the model cannot override it)
```

If nothing passes, the run abstains: it reports an inferred origin as unconfirmed, or proves "no incident" with an `algo.SSpaths` negative proof when every alerting symptom is measured and normal.

</details>

## Architecture

```mermaid
flowchart LR
  subgraph IN["Inputs"]
    AL["Alerts and telemetry windows"]
    CH["Deploys, PRs, flags"]
    LI["Data lineage and warehouse"]
    OR["People, teams, ADRs, runbooks"]
  end

<details><summary>Show the architecture: components, data flow and the safety envelope</summary>


  subgraph FDB["FalkorDB, pinned engine"]
    T1[("tenant_acme")]
    T2[("tenant_globex")]
    BR[("golden, eval, whatif, scratch, audit graphs")]
  end

  subgraph APP["Faultline backend"]
    CREW["Crew of 12 roles: agent/crew.py"]
    GATE["Evidence gate G1-G8: agent/gate.py"]
    ACT["Actions: plan hash, verify, write-back"]
    BRAIN["Company brain: brain/ask.py"]
    PRE["Preflight: preflight/engine.py"]
    RO["graph/ro.py: GRAPH.RO_QUERY + TIMEOUT + LIMIT"]
    WR["graph/writes.py: single-query writes"]
  end

  subgraph OUT["Surfaces"]
    UI["Next.js incident room, brain, preflight, explore"]
    MCP["MCP server: read-only, tenant-bound tools"]
    GHA["GitHub Action: preflight on PRs"]
  end

  GH["GitHub repo: the one approved action"]

  IN -- "ingest and seed" --> WR
  CREW --> RO
  GATE --> RO
  BRAIN --> RO
  PRE --> RO
  ACT --> RO
  ACT --> WR
  ACT <--> GH
  RO --> FDB
  WR --> FDB
  UI <--> APP
  MCP --> RO
  GHA --> PRE
```

Two rules hold everywhere. Reads go through one path, `graph/ro.py`: `GRAPH.RO_QUERY` with a per-query `TIMEOUT` and a literal `LIMIT` sent as n+1 so truncation is detected, as the per-tenant ACL user `ro_<tenant>` when ACL passwords are configured. Writes go through `graph/writes.py`, each a single query that is atomic on its own; the model never holds a write connection. FalkorDB is the only store: `events.jsonl`, `report.md` and the replay files are exports of the graph, and `scripts/lint_single_store.py` enforces this in CI.

The agent's stages:

```mermaid
flowchart LR
  A[Alert] --> R["RECALL: vector index, shared Symptom"]
  R --> L["LOCALIZE: context, SSpaths scope"]
  L --> B["BLAST: algo.BFS, betweenness"]
  B --> H["HYPOTHESIZE: window changes, pageRank, memory prior"]
  H --> I["INVESTIGATE: policy or LLM proposes"]
  I --> G{"GATE v2: G1-G8 read-only queries"}
  G -- "no path or insufficient flow" --> X["rejected, recorded"]
  G -- "nothing explains it" --> U["abstain: inferred origin, unconfirmed"]
  G -- accepted --> C["CONTAIN: WCC, maxFlow min-cut, futures on GRAPH.COPY"]
  C --> W["ROUTE: HarmonicCentrality, bus factor, MSF"]
  W --> P["PLAN: exact action + plan hash"]
  P --> E["EXECUTE, VERIFY: three-valued, two channels"]
  E --> WB["WRITEBACK: one query + separate RO re-read"]
  WB --> LN["LEARN: labelPropagation family, derived runbook"]
```

**The crew.** Each stage is worked by a named, least-privilege role: Triage, Historian, Cartographer, Profiler, the Lead investigator with its five investigators (topology, telemetry, data, change, code), the Gatekeeper, Containment, Dispatcher, Planner, Operator, Auditor and Librarian ([docs/AGENTS.md](docs/AGENTS.md), generated from `agent/crew.py`). Each role is deterministic code with its own tool whitelist, enforced in code; only the lead may use a model, and the Gatekeeper never does. The Operator is the only holder of `execute_action`. Every step is a record in FalkorDB: `(:Run)-[:HAS_TASK]->(:Task)-[:CLAIMED_BY]->(:Agent)`, the graph calls it made (`MADE`) and the hand-off order (`NEXT`). The incident room's Crew board reads it back (`Q-CREW-1`), and "Why do you believe this?" draws the verdict's provenance (`Q-PROV-1`): which agent's call produced which evidence that supports the confirmed cause. Crew records are records, not locks: execution is serialised by the Intent lease, and a crew record never counts as a G7 vote. Per-stage tool whitelists: [docs/STAGE_TOOLS.md](docs/STAGE_TOOLS.md).

</details>

## Graph model

One graph per tenant. Every node carries the base label `Node` plus one domain label, so ids resolve across labels. The core of the model:

<details><summary>Show the graph model: labels, relationships and validity windows</summary>


```mermaid
flowchart LR
  Deploy -- CHANGED --> Service
  FeatureFlag -- GATES --> Service
  Service -- "PROPAGATES_TO {cap, cut_cost}" --> Service2[Service]
  Service -- PROPAGATES_TO --> Datastore
  Service -- "PROPAGATES_TO (cross-domain)" --> Table
  Table -- "PROPAGATES_TO {cap = row share}" --> KPI
  PR -- TOUCHES --> File
  File -- PART_OF --> Service
  Team -- "OWNS, OWNED_AT {from, to}" --> Service
  Person -- "MEMBER_OF, ON_CALL {from, to}" --> Team
  Person -- "COMMITTED {n, last_at}" --> Service
  Decision -- CONSTRAINS --> Service
  Decision -- SUPERSEDES --> Decision
  Runbook -- RUNBOOK_FOR --> Symptom
  Incident -- HAS_SYMPTOM --> Symptom
  Deploy -- CAUSED --> Incident
  Incident -- "RESOLVED_BY (APPLIED only)" --> Action
  Postmortem -- DOCUMENTS --> Incident
  Run -- HAS_TOOL_CALL --> ToolCall
  ToolCall -- PRODUCED_EVIDENCE --> Evidence
  ToolCall -- "SAW (ids returned)" --> Service
  Incident -- HAS_GATE_RUN --> GateRun
  Run -- HAS_TASK --> Task
  Task -- CLAIMED_BY --> Agent
```

- The agent never decides over raw `CALLS` or lineage edges. At ingest each producer writes a derived `PROPAGATES_TO` edge that points the way failure flows, with `cap` (criticality, or row share on lineage) and `cut_cost`.
- Ownership, on-call and decisions carry validity windows (`OWNED_AT {from, to}`, `ON_CALL {from, to}`, `SUPERSEDES`), and calls a past PR introduced carry `valid_from`, so the graph answers as of a date or an incident.
- Incidents, postmortems and runbooks carry `vecf32` embeddings under a vector index; services, tables, runbooks, decisions, postmortems and docs have full-text indexes.
- Run state lives in the same graph: `Run`, `StageEvent`, `ToolCall`, `Evidence`, `Hypothesis`, `GateRun`, `Approval`, `Intent`, `Action`, `Task`/`Agent`, `Session`/`Turn`.

Full ER diagrams, property semantics and validity windows: [docs/GRAPH_MODEL.md](docs/GRAPH_MODEL.md). The live schema, generated from the seeded graphs and checked for drift against the declared model (`graph/schema_model.py`): [docs/GRAPH_SCHEMA.md](docs/GRAPH_SCHEMA.md). Seeded sizes: acme has <!-- claim:repo.acme.services -->21<!-- /claim --> services, <!-- claim:repo.acme.persons -->40<!-- /claim --> people and <!-- claim:repo.acme.incidents -->40<!-- /claim --> past incidents; globex has <!-- claim:repo.globex.services -->200<!-- /claim --> services, <!-- claim:repo.globex.persons -->180<!-- /claim --> people and <!-- claim:repo.globex.incidents -->150<!-- /claim --> past incidents.

</details>

## FalkorDB feature map

Every feature below is called from the listed file. Template paths are under `backend/faultline/graph/templates/`.

| Feature | Used for | File |
|---|---|---|
| `algo.SPpaths` / `algo.SSpaths` | G2 proof path, path multiplicity / upstream scope, suspects, no-incident negative proof | `gate_path.cypher`, `gate_multiplicity.cypher`, `upstream_scope.cypher`, `upstream_suspects.cypher`, `neg_proof.cypher` |
| `algo.maxFlow` (+ `edgeFlows`) | G5 sufficiency; containment min-cut computed from the flows; preflight | `gate_flow.cypher`, `cut_flow.cypher`, `preflight_flow.cypher`, `graph/algo/maxflow.py` |
| `algo.BFS`, `algo.WCC` | blast radius, protected set, preflight impact, alert-storm grouping, what-if on a branch | `blast_radius.cypher`, `protect_set.cypher`, `preflight_impact.cypher`, `storm_wcc.cypher`, `connectivity.cypher`, `whatif_*.cypher` |
| `algo.betweenness`, `algo.pageRank` | chokepoints, preflight risk, node size; investigation order | `chokepoints.cypher`, `betweenness_all.cypher`, `rank_causes.cypher` |
| `algo.HarmonicCentrality`, `algo.MSF` | who fixes it, escalation tree (scratch projections; the projection's pairs, reasons and tie weights are Cypher too) | `harmonic.cypher`, `msf.cypher`, `who_knows.cypher`, `who_reasons.cypher`, `collab_weights.cypher` |
| `algo.labelPropagation` | incident families → derived runbooks | `families.cypher`, `memory/learn.py` |
| Vector index (`vecf32`, `db.idx.vector.queryNodes`) | recall, brain entity seeds, forget proof. HNSW options measured against an exact `vec.cosineDistance` scan (`M 32`, `efConstruction 400`, `efRuntime 100`): recall@10 <!-- claim:vector.recall_at_10.tuned -->1.0<!-- /claim --> on every set, against <!-- claim:vector.recall_at_10.default -->0.9767<!-- /claim --> for the default index | `recall.cypher`, `find_incident_vector.cypher`, `forget_vector_probe.cypher`, `graph/schema.cypher`, [`evals/vector_recall.py`](evals/vector_recall.py) |
| Full-text index (DDL form) | brain tier-1 seeds | `find_*.cypher`, `graph/schema.cypher` |
| `GRAPH.COPY` | golden → tenant and eval clean rooms, what-if branches, one futures branch per containment candidate, the Break it twin, as-of branches for the backtest, Re-arm | `graph/copy.py`, `futures.cypher`, `playground.py` |
| `GRAPH.RO_QUERY` + `TIMEOUT` + ACL users | every read | `graph/ro.py`, `deploy/users.acl.template` |
| `GRAPH.EXPLAIN` / `GRAPH.PROFILE` | text2cypher plan check / the UI Cypher panel | `graph/guard.py`, `graph/ro.py` |
| `GRAPH.CONSTRAINT` MANDATORY / UNIQUE on nodes and edges | <!-- claim:repo.constraints -->15<!-- /claim --> engine-enforced invariants on every golden, tenant, on-call and clean-room graph (`GRAPH.COPY` carries them): evidence provenance, a page's deadline, an approval's plan hash, `PROPAGATES_TO.cap`, every node's id, unique run and intent ids. FalkorDB refuses the violating write | [`graph/constraints.py`](backend/faultline/graph/constraints.py), `graph/writes.py`, `tests/live/test_constraints.py` |
| UDFs (`GRAPH.UDF LOAD`, FalkorDB FLEX, pinned by sha) | fuzzy entity resolution (`flex.text.jaroWinkler`), co-failure coupling strength (`flex.sim.jaccard`) | `find_fuzzy.cypher`, `hidden_coupling.cypher`, `graph/udf.py` |
| Many graphs on one instance | `tenant_*`, `golden_*`, `golden_*_nomem` (memory-off arm), `audit_*` (append-only receipts), `eval_*`, `scratch_*`, `whatif_*` | `graph/tenant.py` |
| Redis ACL users per tenant | `ro_<tenant>` may only `GRAPH.RO_QUERY`/`EXPLAIN` its own keys (S7 checks NOPERM) | `deploy/users.acl.template`, `tests/isolation/` |
| `GRAPH.CONFIG` runtime limits | `TIMEOUT_MAX`, `TIMEOUT_DEFAULT`, `RESULTSET_SIZE`, `MAX_QUEUED_QUERIES` and the per-query memory cap `QUERY_MEM_CAPACITY` (256 MB: a runaway query, from any client including the official MCP server, is stopped by the engine and the engine stays up) applied and verified at seed | `scripts/configure_falkordb.py`, `deploy/docker-compose.yml`, `tests/live/test_mem_cap.py` |
| `avg` / `stDevP` / `percentileCont` aggregates | the gate's anomaly band, computed in the engine (same verdicts as before: the gate bench reproduces its recorded run) | `baseline_band.cypher`, `metric_window_band.cypher`, `agent/datatools.py`, `tests/live/test_band_in_engine.py` |
| Temporal values (`localdatetime`, `duration`, `.dayOfWeek`, `.hour`) | change-freeze windows in the pre-deploy gate: FalkorDB turns the merge time into the policy's local wall clock and holds a PR inside "no payment changes Friday 16:00 to Monday 09:00" | `preflight_freeze.cypher`, `data/gen/policies/acme.yaml`, `preflight/score.py` |
| `dbms.functions()` | text2cypher function allow-list, built from the engine's own catalogue (built-ins plus two vetted UDFs) | `engine_functions.cypher`, `graph/guard.py` |
| `telemetry{graph}` stream + `GRAPH.MEMORY USAGE` | `GET /api/engine/insight`: every query's wait, execution and report time and plan-cache use, per template id, as FalkorDB recorded it (ids and numbers only) | `graph/engine_info.py`, `api.py` |
| `WAITAOF` | the write-back is on disk before VERIFY counts it; a timeout is UNKNOWN, never RESOLVED | `graph/client.py`, `actions/act.py` |
| `intern()` | the telemetry windows' repeated strings (component, metric, kind, source) are stored once by the engine | `graph/writes.py::upsert_nodes`, `tests/live/test_intern.py` |
| Engine without internet egress | prod puts FalkorDB on an internal-only Docker network with no route to the internet (defence in depth), so no query can reach out | `deploy/docker-compose.prod.yml`, `scripts/egress_check.py` |
| Edge validity windows + `SUPERSEDES` | as-of answers: owner, on-call, decisions and runbooks at a date or an incident's onset; the topology at a PR's merge | `owner_at.cypher`, `beliefs_at.cypher`, `timeline.cypher`, `preflight_impact_asof.cypher`, `topology_at.cypher` |
| Pattern comprehensions + bounded variable-length paths | G1 grounding, alert grouping, family fixes, preflight components (the template lint rejects unbounded paths) | `gate_grounding.cypher`, `primary_symptoms.cypher`, `preflight_components.cypher` |
| Single-query atomic writes | every state change (approval + intent, write-back, claims, forget) is one query | `graph/writes.py` |
| `db.meta.stats()`, `db.indexes()` | the `graph_schema` tool, MCP resources, schema drift check | `schema_*.cypher`, `graph/schema_introspect.py`, `scripts/check_schema_drift.py` |
| Official FalkorDB MCP server | raw read-only access for judges | `.mcp.json` (`@falkordb/mcpserver@1.3.0`, strict read-only) |
| `@falkordb/canvas` | the UI's Explore view of the failure-flow graph (node size = betweenness) | `frontend/src/components/explore/FalkorCanvas.tsx` |
| FalkorDB Browser | the same graph, inspected directly: [proof path](docs/media/falkordb-browser-path.png), [decisions constraining payment](docs/media/falkordb-browser-decisions.png) | `docs/media/` |

All <!-- claim:repo.algorithms -->10<!-- /claim --> procedures are resolved on the pinned engine by `make smoke` and recorded in `graph/algo/resolved.json`; procedure names and call forms live only in [`graph/algo/registry.py`](backend/faultline/graph/algo/registry.py) ([docs/FALKORDB_COMPAT.md](docs/FALKORDB_COMPAT.md)). The engine is `falkordb/falkordb:6.0.2`, pinned by digest. The engine bugs we hit are written up as upstream drafts in [docs/upstream/](docs/upstream).

## The graph is load-bearing

![Remove both path and flow checks and true causes are lost; remove one and the other covers for it](docs/media/charts/ladder.svg)

![Same graph questions, same answers: FalkorDB against recursive SQL](docs/media/charts/vs_sql.svg)

Method and numbers for both charts: [docs/PROOF.md, Why FalkorDB](docs/PROOF.md#why-falkordb-what-the-graph-engine-itself-contributes).

`tests/live/test_algo_load_bearing.py` perturbs, on a clean-room `GRAPH.COPY`, exactly what each algorithm reads, and asserts that the decision changes:

| Algorithm (MCP tool) | Decision it makes | Perturbation → flip |
|---|---|---|
| `algo.BFS` (`blast_radius`) | impact set, verification collateral | cut payment→checkout → checkout leaves the impact set |
| `algo.SPpaths` (`causal_paths`) | G2 pass/fail | remove the edge → "no path, no claim" |
| `algo.SSpaths` (`reachable_from_changes`) | NO_INCIDENT vs refuse | cut the path → negative proof accepted |
| `algo.maxFlow` (`impact_bound`) | G5 keep/eliminate | lower one capacity → sufficient becomes insufficient |
| `algo.maxFlow` (`containment_cut`) | which edge to cut | change one `cut_cost` → a different min-cut |
| `algo.WCC` (`connectivity_check`) | whether a cut is needed at all | disconnect → no containment step |
| `algo.betweenness` (`chokepoints`) | preflight risk, chokepoints | remove the top hub's calls → a new top chokepoint |
| `algo.pageRank` (`rank_causes`) | investigation order | add dependencies → a new first suspect |
| `algo.HarmonicCentrality` (`who_fixes`) | who is paged first | remove the top person's work → a new first responder |
| `algo.MSF` (`escalation_tree`) | who is looped in, in what order | drop one collaboration → a different tree |
| `algo.labelPropagation` (`incident_families`) | derived runbook (procedural memory) | split the family → no runbook |

At the outcome level:

| Taken out | What happens | Number |
|---|---|---|
| FalkorDB (arm A4, `FAULTLINE_DISABLE_GRAPH=true`) | the run cannot start and the UI says so; nothing is guessed | confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes |
| The max-flow check G5 (arm A3-noG5) | S2 can no longer be decided: the stale FX feed survives, so the run escalates rather than guessing; S1 is still decided because the origin test rejects the email deploy too | top-1 <!-- claim:arm.A3.top1 -->1.0<!-- /claim --> → <!-- claim:arm.A3-noG5.top1 -->0.8<!-- /claim --> |
| `algo.SPpaths` and `algo.maxFlow` together (capability ladder, second gate-bench seed) | each covers for the other alone; without both, true causes are lost to abstention | right cause <!-- claim:ladder.full.b.right_cause -->65<!-- /claim --> → <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim --> of <!-- claim:ladder.neither.b.confirm_cases -->65<!-- /claim --> |
| Any one safety check (mutation testing) | each mutant weakens one gate or action rule; the test suite must catch it | <!-- claim:mutation.killed -->41<!-- /claim -->/<!-- claim:mutation.mutants -->41<!-- /claim --> mutants caught |

A4 shows the graph is load-bearing; it is not a measurement of a graph-free agent, because the product fails closed instead of degrading.

## Results

Keyless arms run on fresh `GRAPH.COPY` clean rooms over scenarios S1, S2, S3, S1b, S3b, S12 (abstention) and the controls S4D and S4S. The investigator is deterministic, so N = 3 shows reproducibility, not variance; arm N runs once. Method and expectations were written down first: [evals/PREREGISTRATION.md](evals/PREREGISTRATION.md). Every table is generated into [evals/RESULTS.md](evals/RESULTS.md) from `evals/results/` and never edited by hand.

| Arm | What it gets | Top-1 | False blame (on scenarios with a true cause) | Abstention (S4D, S4S, S12) |
|---|---|---|---|---|
| N: naive recency (also A4's "ungated guess") | the list of changes as files | <!-- claim:arm.N.top1 -->0.1<!-- /claim --> (ties scored 1/k) | <!-- claim:arm.N.false_blame_rate -->1.0<!-- /claim --> | <!-- claim:arm.N.abstention_correct_rate -->0.0<!-- /claim --> |
| V: vector only (cosine in FalkorDB over change-title embeddings) | the incident's vector + the changes' titles | <!-- claim:arm.V.top1 -->0.4<!-- /claim --> | <!-- claim:arm.V.false_blame_rate -->0.6<!-- /claim --> | <!-- claim:arm.V.abstention_correct_rate -->0.0<!-- /claim --> |
| T: telemetry only (the change on the most anomalous component; no topology) | the window's changes + their components' error rates | <!-- claim:arm.T.top1 -->0.9<!-- /claim --> (ties scored 1/k) | <!-- claim:arm.T.false_blame_rate -->0.2<!-- /claim --> | <!-- claim:arm.T.abstention_correct_rate -->0.0<!-- /claim --> |
| A2: graph, memory off | graph tools | <!-- claim:arm.A2.top1 -->1.0<!-- /claim --> | <!-- claim:arm.A2.false_blame_rate -->0.0<!-- /claim --> | <!-- claim:arm.A2.abstention_correct_rate -->1.0<!-- /claim --> |
| A3: graph + memory (the product) | everything | <!-- claim:arm.A3.top1 -->1.0<!-- /claim --> | <!-- claim:arm.A3.false_blame_rate -->0.0<!-- /claim --> | <!-- claim:arm.A3.abstention_correct_rate -->1.0<!-- /claim --> |
| A3-noG5: the product without the max-flow check | everything except G5 | <!-- claim:arm.A3-noG5.top1 -->0.8<!-- /claim --> | <!-- claim:arm.A3-noG5.false_blame_rate -->0.0<!-- /claim --> | <!-- claim:arm.A3-noG5.abstention_correct_rate -->1.0<!-- /claim --> |
| A4: FalkorDB off | the same agent; the run cannot start (fails closed) | confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> | <!-- claim:arm.A4.false_blame_rate -->0.0<!-- /claim --> | <!-- claim:arm.A4.abstention_correct_rate -->0.0<!-- /claim --> (cannot prove a no-incident) |

What arm T shows, plainly: on these scenarios a plain anomaly heuristic already finds most service causes, because the cause's own component is the most anomalous one. The graph earns its keep where that heuristic cannot go: the data incident (S2, where the distractor ties), the controls and the abstention (T can never say "no change explains this"), and the max-flow rejection of a look-alike that has a path. Grounding (G1) is <!-- claim:arm.A3.grounded_rate -->1.0<!-- /claim -->.

Headline results (method for each line: [docs/EVALS.md](docs/EVALS.md)):

| Question | Result |
|---|---|
| Does the gate decide right on generated incidents? | gate bench <!-- claim:gate_bench.correct -->100<!-- /claim -->/<!-- claim:gate_bench.cases -->100<!-- /claim --> (development seed), <!-- claim:gate_bench_heldout.correct -->100<!-- /claim -->/<!-- claim:gate_bench_heldout.cases -->100<!-- /claim --> (second seed) and <!-- claim:seeds.gate.correct -->300<!-- /claim -->/<!-- claim:seeds.gate.cases -->300<!-- /claim --> on <!-- claim:seeds.gate.seeds -->3<!-- /claim --> seeds generated for this audit, 0 wrong blames; strict, with a bystander named "not confident" counted wrong: <!-- claim:gate_bench.correct_strict -->96<!-- /claim -->, <!-- claim:gate_bench_heldout.correct_strict -->98<!-- /claim --> and <!-- claim:seeds.gate.correct_strict -->296<!-- /claim -->. This bench is a conformance test (healthy look-alikes; its verdicts follow the gate's rules): a thresholded telemetry heuristic scores <!-- claim:seeds.gate.Tplus.right_strict -->194<!-- /claim -->/<!-- claim:seeds.gate.cause_cases -->195<!-- /claim --> causes with <!-- claim:seeds.gate.Tplus.wrong_any -->1<!-- /claim --> wrong blame on the new seeds |
| Multi-hop causes and innocent deploys downstream? | deep bench, fresh seed: right cause <!-- claim:deep.fresh.all.right_cause -->51<!-- /claim -->/<!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim -->, <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds, <!-- claim:deep.fresh.all.abstained -->89<!-- /claim --> abstained; on <!-- claim:seeds.deep.seeds -->3<!-- /claim --> new seeds <!-- claim:seeds.deep.right_cause -->136<!-- /claim -->/<!-- claim:seeds.deep.cause_cases -->300<!-- /claim --> and <!-- claim:seeds.deep.wrong_confident -->0<!-- /claim --> in <!-- claim:seeds.deep.cases -->420<!-- /claim -->, with <!-- claim:seeds.deep.accepted_nc.bystander -->24<!-- /claim --> innocent changes named "not confident". Telemetry only is more often right (<!-- claim:deep.fresh.all.T.right_strict -->85<!-- /claim -->/<!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim --> and <!-- claim:seeds.deep.T.right_strict -->249<!-- /claim -->/<!-- claim:seeds.deep.cause_cases -->300<!-- /claim -->) and wrong in <!-- claim:deep.fresh.all.T.wrong_any -->55<!-- /claim --> and <!-- claim:seeds.deep.T.wrong_any -->171<!-- /claim --> worlds |
| Does it hold on the second tenant (globex, 200 services)? | independent-parameter worlds: right cause <!-- claim:world_globex.right_cause -->106<!-- /claim -->/<!-- claim:world_globex.cause_cases -->117<!-- /claim -->, <!-- claim:world_globex.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:world_globex.cases -->200<!-- /claim --> worlds. Telemetry only: right <!-- claim:world_globex.T.right_strict -->107<!-- /claim -->, wrong <!-- claim:world_globex.T.wrong_any -->93<!-- /claim -->; thresholded (T+): right <!-- claim:world_globex.Tplus.right_strict -->107<!-- /claim -->, wrong <!-- claim:world_globex.Tplus.wrong_any -->1<!-- /claim -->, as good as the gate when look-alikes are mostly healthy |
| What if the graph is wrong about the world? | wrong-confident blames: <!-- claim:mismatch.caps.wrong_confident -->0<!-- /claim --> (caps ±50%), <!-- claim:mismatch.hidden.wrong_confident -->0<!-- /claim --> (hidden edge), <!-- claim:mismatch.stale.wrong_confident -->0<!-- /claim --> (stale edge), <!-- claim:mismatch.all.wrong_confident -->0<!-- /claim --> (all three) | <!-- noclaim: ±50% is the pre-registered perturbation size, not a result -->
| What does each FalkorDB algorithm buy? | with healthy look-alikes (second-seed gate bench), each algorithm covers for the other: right cause <!-- claim:ladder.full.b.right_cause -->65<!-- /claim -->/<!-- claim:ladder.full.b.confirm_cases -->65<!-- /claim --> full, <!-- claim:ladder.no_maxflow.b.right_cause -->65<!-- /claim --> without `algo.maxFlow`, <!-- claim:ladder.no_sppaths.b.right_cause -->65<!-- /claim --> with `algo.SPpaths` swapped for connectivity, <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim --> without both. When the look-alike is itself faulty (decisive bench), `algo.maxFlow` decides alone: right cause <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim -->/<!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> with it, <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim --> without; telemetry only <!-- claim:decisive.T.g5_only.right_strict -->13<!-- /claim -->. Wrong-confident 0 on every rung (we predicted it would rise) |
| Where does it break? | <!-- claim:curve.wrong_confident_max -->0<!-- /claim --> confident wrong blames at any of <!-- claim:curve.points -->21<!-- /claim --> stress points. Not on noise up to ×16 (<!-- claim:curve.noise.16.correct -->100<!-- /claim -->/100 correct) or ×10 duplicate alerts (<!-- claim:robustness.duplicates.10.correct -->100<!-- /claim -->); it bends with missing telemetry (<!-- claim:curve.missing.0.2.correct -->83<!-- /claim --> correct with a fifth of components dark, <!-- claim:curve.missing.0.5.correct -->53<!-- /claim --> with half, every loss an abstention) and with heavy noise (×64: <!-- claim:curve.noise.64.correct -->82<!-- /claim -->). It breaks on small faults: scaled to a few percentage points of error, the gate declares "no incident" while the alert fires (correct <!-- claim:curve.effect.0.05.correct -->54<!-- /claim --> at ×0.05, <!-- claim:curve.effect.0.025.correct -->15<!-- /claim --> at ×0.025): a missed incident, not a wrong blame <!-- noclaim: ×0.05/×0.025 are knob settings --> |
| Is the graph better context for an agent than vector RAG? | `context_pack` on <!-- claim:ctx.busy0.worlds -->110<!-- /claim --> worlds, true cause's rank at 1,000 tokens with 30 unrelated deploys (MRR): <!-- claim:ctx.busy30.b1000.GA.mrr -->0.6598<!-- /claim --> vs <!-- claim:ctx.busy30.b1000.TR.mrr -->0.5606<!-- /claim --> ranking by telemetry without the graph, <!-- claim:ctx.busy30.b1000.V.mrr -->0.4226<!-- /claim --> vector RAG and <!-- claim:ctx.busy30.b1000.R.mrr -->0.0768<!-- /claim --> recency; paired difference over telemetry alone <!-- claim:ctx.busy30.b1000.GA_minus_TR.mrr_diff -->0.0991<!-- /claim --> [<!-- claim:ctx.busy30.b1000.GA_minus_TR.ci_lo -->0.06<!-- /claim -->–<!-- claim:ctx.busy30.b1000.GA_minus_TR.ci_hi -->0.1424<!-- /claim -->], and only <!-- claim:ctx.busy0.b1000.GA_minus_TR.mrr_diff -->0.0136<!-- /claim --> in a quiet window. Graph distance alone (<!-- claim:ctx.busy30.b1000.G.mrr -->0.385<!-- /claim -->) was no better than vector |
| Does memory ever change the answer? | after a verified fix teaches a missing link: <!-- claim:learning.i2_learned_correct -->24<!-- /claim -->/<!-- claim:learning.cases -->24<!-- /claim --> next incidents correct (<!-- claim:learning.i2_fresh_correct -->24<!-- /claim --> with a fresh world seed) vs <!-- claim:learning.i2_control_correct -->2<!-- /claim --> without; wrong guesses taught <!-- claim:learning.wrong_guess_proposals -->0<!-- /claim --> links. The eval's human is an oracle that names the true cause: this tests the mechanism, not a human's judgement |
| Do the predicted futures come true? | <!-- claim:futures.bench.cut.agree -->148<!-- /claim -->/<!-- claim:futures.bench.cut.definite -->148<!-- /claim --> measured cut predictions match the world, <!-- claim:futures.bench.cut.false_assurance -->0<!-- /claim --> false assurances |
| Are the safety checks really tested? | <!-- claim:mutation.killed -->41<!-- /claim -->/<!-- claim:mutation.mutants -->41<!-- /claim --> mutants caught |
| Kill -9 in the middle of an action? | settled exactly once: <!-- claim:chaos.exactly_once -->True<!-- /claim -->, write-back <!-- claim:chaos.writeback -->7/7<!-- /claim --> |
| Many responders approve at once? | <!-- claim:contention.responders -->24<!-- /claim --> concurrent approvals: <!-- claim:contention.same.accepted -->1<!-- /claim --> accepted, <!-- claim:contention.same.refused -->23<!-- /claim --> refused, <!-- claim:contention.same.prs -->1<!-- /claim --> PR |
| Company brain | <!-- claim:brain.correct -->33<!-- /claim -->/<!-- claim:brain.questions -->33<!-- /claim --> on our own questions, including <!-- claim:brain.unanswerable_honest -->6<!-- /claim --> of <!-- claim:brain.unanswerable -->6<!-- /claim --> unanswerable ones declined honestly; on a paraphrase of each question <!-- claim:brain_para.correct -->30<!-- /claim -->/<!-- claim:brain_para.questions -->33<!-- /claim -->, and <!-- claim:brain_para.cites_ok -->30<!-- /claim --> with every expected citation. Routing is two-stage: keyword patterns first, and only when none matches, FalkorDB (vector + full-text over seeded question examples, refusing weak matches); the paraphrase set is the one this was built on, so it is not blind. **On a blind set** written by an agent that never saw the router: <!-- claim:brain_blind.s2.hybrid.correct -->24<!-- /claim -->/<!-- claim:brain_blind.s2.hybrid.questions -->40<!-- /claim -->, against <!-- claim:brain_blind.s2.keyword_router.correct -->19<!-- /claim -->/<!-- claim:brain_blind.s2.keyword_router.questions -->40<!-- /claim --> for keyword routing alone |
| Same answers as SQL? | the gate's lookups vs DuckDB recursive SQL on the same edges at 1k services: <!-- claim:perf.1k.reach_set.equal -->10<!-- /claim -->/<!-- claim:perf.1k.reach_set.instances -->10<!-- /claim --> reach sets and <!-- claim:perf.1k.shortest_causal_path.equal -->10<!-- /claim -->/<!-- claim:perf.1k.shortest_causal_path.instances -->10<!-- /claim --> shortest causal paths agree (<!-- claim:perf.1k.shortest_causal_path.non_empty -->5<!-- /claim --> have a path; the rest agree there is none); both are milliseconds at this size, so no speed claim (times in [docs/PROOF.md](docs/PROOF.md#why-falkordb-what-the-graph-engine-itself-contributes)) |
| How fast? | a full scenario run (deterministic investigator, clean room) p50 <!-- claim:arm.A3.seconds_p50 -->0.84<!-- /claim --> s; the G2 query p50 <!-- claim:profile.Q-GATE-1.engine_ms_p50 -->0.025<!-- /claim --> ms engine time; a brain answer p50 <!-- claim:brain.ms_p50 -->11.8<!-- /claim --> ms; an alert is visible to decisions <!-- claim:perf.fresh.alert.p50_ms -->0.727<!-- /claim --> ms after the write |
| Scale | <!-- claim:scale.10k.services -->10000<!-- /claim --> services, <!-- claim:scale.10k.nodes -->296261<!-- /claim --> nodes, <!-- claim:scale.10k.edges -->1097675<!-- /claim --> edges: decided correctly (<!-- claim:scale.10k.correct -->True<!-- /claim -->) in <!-- claim:scale.10k.run_s -->34.88<!-- /claim --> s end to end, most of it the futures stage (one `GRAPH.COPY` branch per containment option); the gate sweep that decides takes <!-- claim:scale.10k.sweep_ms_p50 -->463.421<!-- /claim --> ms (p50) |
| Would preflight have caught past bad PRs? | mixed, reported as is: AUROC <!-- claim:backtest.globex.full.all.auroc -->0.8075<!-- /claim --> on globex, <!-- claim:backtest.acme.full.all.auroc -->0.5179<!-- /claim --> (chance) on acme |
| Is the method portable? | the four-query skill names the gate's cause in <!-- claim:skill.named_same -->4<!-- /claim -->/<!-- claim:skill.cause_scenarios -->5<!-- /claim --> scenarios that have one (its miss abstains), abstains with the gate in <!-- claim:skill.abstain_same -->3<!-- /claim -->/<!-- claim:skill.abstain_scenarios -->3<!-- /claim -->, and eliminated the gate's cause <!-- claim:skill.cause_eliminated -->0<!-- /claim --> times |

**LLM arms** ([evals/llm_arms.py](evals/llm_arms.py), `claude-opus-5-5`, side file `evals/results/llm_arms.json`): given the alert, per-minute telemetry for every service, the change list with its diff facts and, for data incidents, the warehouse comparison and invariant results, the model alone (A0) got the right verdict in <!-- claim:arm.A0.outcome_correct.k -->23<!-- /claim --> of <!-- claim:arm.A0.outcome_correct.n -->24<!-- /claim --> trials [<!-- claim:arm.A0.outcome_correct.ci_lo -->80%<!-- /claim -->–<!-- claim:arm.A0.outcome_correct.ci_hi -->99%<!-- /claim -->] across the 8 scenarios (3 trials each), with <!-- claim:arm.A0.scen.wrong_blame.k -->0<!-- /claim --> wrong blames; with vector-RAG context (A1) <!-- claim:arm.A1.outcome_correct.k -->23<!-- /claim --> of <!-- claim:arm.A1.outcome_correct.n -->24<!-- /claim -->. Faultline driven by the same model (A3L) got <!-- claim:arm.A3L.outcome_correct.k -->8<!-- /claim --> of <!-- claim:arm.A3L.outcome_correct.n -->8<!-- /claim --> [<!-- claim:arm.A3L.outcome_correct.ci_lo -->68%<!-- /claim -->–100 %]. **On our hand-written scenarios, a strong model with good evidence is as accurate as the gate; on the adversarial worlds it is not safe.** On the same <!-- claim:llm_deep.deep.all.cases -->140<!-- /claim --> deep-bench worlds it names the right cause more often than Faultline (<!-- claim:llm_deep.deep.all.right_cause -->66<!-- /claim --> of 100) but confidently blames an innocent change in <!-- claim:llm_deep.deep.all.wrong_confident -->37<!-- /claim -->; on the <!-- claim:llm_deep.decisive.all.cases -->40<!-- /claim --> decisive worlds, where only `algo.maxFlow` or `algo.SPpaths` can reject the look-alike, it blames an innocent change in <!-- claim:llm_deep.decisive.all.wrong_confident -->7<!-- /claim --> (Faultline: 0). What the graph adds there is not accuracy: it is a proof anyone can re-run (the path and the flow bound, as Cypher), no tokens and well under a millisecond per check against a median <!-- claim:arm.A0.tokens_median -->2522<!-- /claim --> tokens per LLM decision, the same answer every time (the model missed S3b in one trial of three), and the approved, verified action. An earlier version of this test had two flaws (no way to answer "an incident no listed change explains", and no warehouse evidence on the data control); both are fixed in the prompt used here. <!-- noclaim: 55 is deep.fresh.all.T.wrong_any, tagged above -->

## What makes it different

| Property | How it works | Evidence |
|---|---|---|
| Graph proof before any claim | G2 needs an `algo.SPpaths` row from the change to every symptom | [`gate_path.cypher`](backend/faultline/graph/templates/gate_path.cypher); `tests/live/test_algo_load_bearing.py::test_sppaths_decides_g2` |
| A capacity bound on every suspect | G5: joint `algo.maxFlow` × path multiplicity must cover the observed share | `D-fx-pause-7` max flow <!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> < <!-- claim:s2.D-fx-pause-7.needed -->0.8<!-- /claim -->; property test `tests/graph/test_g5_bound_property.py` |
| Abstention instead of guessing | not confident, inferred origin, or a proven no-incident; missing telemetry is never read as "normal" (N0) | gate bench, second seed <!-- claim:gate_bench_heldout.correct -->100<!-- /claim -->/<!-- claim:gate_bench_heldout.cases -->100<!-- /claim -->; deep bench <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> wrong-confident |
| Three-valued verification | GitHub main re-read plus telemetry for every symptom and collateral; UNKNOWN goes to a human | S9 → <!-- claim:s9.verdict -->UNKNOWN<!-- /claim -->, success written <!-- claim:s9.success_written -->False<!-- /claim --> |
| Two-step approval bound to a plan hash | choosing ≠ approving; approval quotes the hash of the exact diff and is exclusive in one query | [`actions/act.py`](backend/faultline/actions/act.py), `tests/live/test_actions.py`; <!-- claim:contention.same.accepted -->1<!-- /claim --> of <!-- claim:contention.responders -->24<!-- /claim --> racing approvals lands |
| Write-back and warm recall in the same graph | the verdict, cause, postmortem and decision are written in one query and re-read on a separate RO connection; the next incident recalls them | write-back <!-- claim:s1.writeback -->7/7<!-- /claim -->; S1b warm prior <!-- claim:memory.warm_prior -->0.8423<!-- /claim --> |
| Provenance from verdict to tool call | every evidence item records its template, Cypher, params and digest; `Q-PROV-1` walks verdict → evidence → tool call → agent | [`run_provenance.cypher`](backend/faultline/graph/templates/run_provenance.cypher); grounding <!-- claim:arm.A3.grounded_rate -->1.0<!-- /claim --> |
| Pre-deploy gate on the same graph | a PR is scored from BFS impact, betweenness, past incidents, contradicted decisions, bus factor and missing guardrails | S6 → <!-- claim:s6.verdict -->block<!-- /claim --> (risk <!-- claim:s6.risk -->0.8<!-- /claim -->); [`deploy/github-action/`](deploy/github-action/faultline-preflight.yml) |
| Company brain on the same graph | as-of answers about owners, decisions and on-call; every cited id must have been returned by that question's own queries | <!-- claim:brain.correct -->33<!-- /claim -->/<!-- claim:brain.questions -->33<!-- /claim --> on our wording, <!-- claim:brain_para.correct -->30<!-- /claim -->/<!-- claim:brain_para.questions -->33<!-- /claim --> reworded (the development set, not blind); <!-- claim:brain_blind.s2.hybrid.correct -->24<!-- /claim -->/<!-- claim:brain_blind.s2.hybrid.questions -->40<!-- /claim --> on a blind set; `Q-CITE-1` |
| Per-tenant isolation | one graph and one ACL user per tenant; the hosted MCP binds a key to one tenant | S7 isolation checks: <!-- claim:s7.passed -->34<!-- /claim --> passed, <!-- claim:s7.failed -->0<!-- /claim --> failed |
| MCP for any agent | the agent's own read-only tools, each returning the Cypher, params, timing and a row digest | <!-- claim:repo.mcp_tools -->57<!-- /claim --> tools, <!-- claim:repo.mcp_tools_hosted -->51<!-- /claim --> of them exposed over Streamable HTTP; [docs/MCP.md](docs/MCP.md) |

## Context for any agent

Vector search finds the entry points; FalkorDB walks from them to the changes upstream of the alert (ranked by the anomaly the graph's telemetry measured on each), their causal paths, the owners and who can fix it, the decisions that constrain them, and what fixed it last time. One MCP call packs that to a token budget, with the query behind every line.

`context_pack(text="checkout errors are elevated", targets=["checkout"], budget_tokens=500)` on the hero incident's clean room, first lines verbatim:

> - `[change] change D-pay-417 (deploy) on payment (error-rate excess +0.403), 1 hop(s) upstream of checkout, 3 min before` ‹Q-CTX-RANK› <!-- noclaim: verbatim output of one pack on the S1 clean room -->
> - `[change] change D-email-88 (deploy) on email (error-rate excess +0.001), 1 hop(s) upstream of checkout, 3 min before` ‹Q-CTX-RANK› <!-- noclaim: verbatim output of one pack on the S1 clean room -->
> - `[path] causal path: D-pay-417 → payment → checkout` ‹Q-GATE-1›
> - `[people] who can fix payment: p-030, p-004, p-017, p-036, p-038 (team team-payments)` ‹Q-ORG-1›
> - `[decision] decision ADR-012 constrains payment: Payment client timeout must stay ≤ 2000 ms` ‹Q-DEC-ABOUT› <!-- noclaim: verbatim output of one pack on the S1 clean room -->

**MCP.** `make mcp` serves every product read as a typed, tenant-bound tool over stdio, plus the schema, query and weights resources and the investigate, preflight and ask-brain prompts. `make mcp-http` serves the same tools over Streamable HTTP with a bearer key bound to one tenant; it is deployed at `https://13-203-185-119.sslip.io/mcp` (read-only, rate-limited). Tools that build scratch or branch graphs stay internal, and the MCP service gets no engine credential. The official FalkorDB MCP server is also configured, strict read-only, in [`.mcp.json`](.mcp.json). Details: [docs/MCP.md](docs/MCP.md).

## Memory, company brain, preflight, coordination

- **Memory** recalls precedents by vector, then confirms them structurally; it reorders and never decides (gate verdicts identical cold vs warm: <!-- claim:memory.gate_verdicts_identical -->True<!-- /claim -->).
- **Company brain** answers who owns, knows and decided, and what was true *as of* a date or incident, citing only node ids its own queries returned (<!-- claim:brain.correct -->33<!-- /claim -->/<!-- claim:brain.questions -->33<!-- /claim --> on our question set; <!-- claim:brain_para.correct -->30<!-- /claim -->/<!-- claim:brain_para.questions -->33<!-- /claim --> when each question is reworded, on the development set its router was built on). On a blind set it loses to FalkorDB's own GraphRAG-SDK (its default strategies and prompts on claude-haiku-4-5, four disclosed changes: a local embedder, the full-text DDL fix sent upstream as #345, one shared extractor, longer retries; its own FalkorDB graph over the same knowledge): <!-- claim:graphrag.s2.sdk.correct -->32<!-- /claim -->/<!-- claim:graphrag.s2.questions -->40<!-- /claim --> against the brain's <!-- claim:graphrag.s2.fl.correct -->24<!-- /claim -->/40 (paired p <!-- claim:graphrag.s2.paired.mcnemar_p -->0.12<!-- /claim -->), at US$<!-- claim:graphrag.s2.sdk.usd_per_question -->0.009<!-- /claim --> and <!-- claim:graphrag.s2.sdk.s_p50 -->3.1<!-- /claim --> s per answer ([evals](docs/EVALS.md#company-brain-vs-falkordbs-graphrag-sdk-pre-registered-2026-10-17)).
- **Preflight** blocks a risky PR from the same graph (S6 → <!-- claim:s6.verdict -->block<!-- /claim -->).
- **Coordination** uses atomic claims in one query (<!-- claim:s13.lost_updates -->0<!-- /claim --> lost updates under contention).

<details><summary>Show memory, the company brain, preflight and coordination in detail</summary>



**The company brain (T3), answered by the live deployment.** Every `[id]` is a node a read-only query of that question returned; the brain cannot cite anything else.

> **Who decided the payment timeout, and are they still here?**
> [ADR-012] Payment client timeout must stay ≤ 2000 ms: active, and still current (nothing supersedes it). Decided by [p-004] Dorian Marrowby (still on the owning team), [p-022] Vesna Hollowell (still here, another team). [ADR-013] Payment client keeps ≥ 2 retries: active, and still current. Decided by the same two people.

> **Which revenue-path services lack a runbook or owner?**
> 6 revenue-path services lack a guardrail: [cart], [currency], [frontend], [frontend-proxy] and [shipping] (tier 1) and [quote] (tier 2) have no current runbook.

The same answer drawn as a graph (who decided, the decisions, what they constrain):

<img src="docs/screenshots/20-brain-answer-graph.png" width="760" alt="A company-brain answer drawn as a graph: the people who decided, the decisions, and the components they constrain">

<details><summary><b>How memory, the brain, preflight and coordination work</b></summary>

**Memory (T1/T2).**
- **Recall.** The incident's own vector is looked up in the FalkorDB vector index (`db.idx.vector.queryNodes`), then confirmed structurally through a shared `(:Symptom)` node. It never relies on similarity alone.
- **Families.** Incident families come from `algo.labelPropagation`. When a family has ≥ 2 incidents fixed the same APPLIED way, it is consolidated into a derived runbook with `DERIVED_FROM` provenance. Salience decays, except for incidents with an applied fix. A NOT_APPLIED attempt is remembered too.
- **Measured on S1b**, a repeat payment regression in the same graph after S1 was resolved: the warm run's top precedent is S1 (<!-- claim:memory.warm_top_precedent_is_s1 -->True<!-- /claim -->), the derived runbook comes first (<!-- claim:memory.derived_runbook_first -->True<!-- /claim -->), the family prior rises from <!-- claim:memory.cold_prior -->0.7681<!-- /claim --> to <!-- claim:memory.warm_prior -->0.8423<!-- /claim -->, and gate verdicts stay identical (<!-- claim:memory.gate_verdicts_identical -->True<!-- /claim -->).
- **Forget with a receipt (S10).** A dry run lists exactly what one document alone produced. Execution then requires a token bound to that exact set, and a `ForgetReceipt` is written to `audit_<tenant>`. Proof follows: the forgotten vectors no longer come back from the index, and re-asking the question no longer cites the forgotten decision.

**Company brain (T3).** Tier-1 seeds (id, full-text) → tier-2 templates → tier-3 guarded text2cypher (last resort, LLM mode). Every `[id]` in an answer must have been *seen* by a tool call of that question's own run, and a read-only query decides (`Q-CITE-1`). On-camera questions:
- "Who has worked on payment?"
- "What did we decide about payment timeouts, and is it still current?" (SUPERSEDES head)
- "Which revenue-path services lack a runbook or owner?" (a set difference)
- "What breaks if productcatalog goes down?"

Session turns persist in `(:Session)-[:HAS_TURN]->(:Turn)`, so a follow-up in a new session resolves from history.

**Company brain over time.** Ownership, on-call and decisions carry validity windows in the graph (`OWNED_AT {from, to}`, `ON_CALL {from, to}`, `SUPERSEDES`), so the brain can answer as of a date or an incident:
- "Who owned fraud-detection during inc-h002?" gives the team then, the team now, and the people from the old team who worked on it, who still hold the context (`owner_at`, Q-OWN-AT + Q-OWN-PEOPLE).
- "What did we know about product-catalog as of 2025-11-01?" gives the decision in force *then* (ADR-009, later superseded), with the owner, on-call and runbooks in effect (`beliefs_at`, Q-ASOF-1).
- "What is the history of fraud-detection?" merges deploys, incidents, alerts, ownership changes, decisions and runbook reviews in one timeline (`component_timeline`).
- "Who decided the payment timeout, and are they still here?" names the people who DECIDED each decision and whether each is still active and still on the owning team (`decisions_about`, Q-DEC-PEOPLE).
- "Where is our knowledge stale?" (`knowledge_health`) finds:
  - runbooks not reviewed for `knowledge.stale_days` (90 in `weights.yaml`), or written before the current owner took over;
  - components that changed hands with no runbook since, and who from the previous team to ask, or that nobody who worked on it is left;
  - active decisions whose components changed owner, or that incident causes violated, or whose deciders have all left (Q-DEC-ORPHAN);
  - **edges the graph is probably missing.** Component pairs co-fail repeatedly in the incident history with no failure path between them (`hidden_coupling`, Q-COUPLE-1). On acme, incidents caused at `recommendation` repeatedly hit `product-catalog`, yet failure is only modelled flowing the other way. This is a finding to confirm, never a cause: the gate still needs a path.

**Inside the incident.** After the gate decides, the run also reports four things, each a template:
- **Why the alerts missed it.** For every hop of the proven chain: did an alert fire, and when (Q-CHAIN-MON)?
- **Who to notify** (Q-NOTIFY-1). These are the teams owning anything in the blast radius, plus who is on call for them now, which is different from who fixes it.
- **Who owned the changed component when the change shipped** (Q-OWN-AT).
- **What the confirmed cause does not explain.** Anomalies measured this run that are not downstream of it (Q-RESIDUE-1, advisory). On the hero S1, the small recommendation error spike from the same-minute decoy deploy is reported as "another fault may be active", not hidden.

Containment options are reordered by what worked before: a Beta-smoothed success rate per action kind over past incidents sharing a symptom, computed in Cypher (Q-REM-1). Each option gets a reason line ("rollback worked k/n times on incidents sharing this symptom"). It reorders only; the human still chooses and approves.

**Preflight (Mode B).** A PR is ingested as `(:PR)-[:TOUCHES]->(:File)` plus ChangeFacts extracted from config diffs. The preflight then weighs BFS impact, betweenness, past incidents its components caused, active decisions it contradicts (Q-DEC-1), bus factor and missing guardrails. From these it computes a risk score (weights in `weights.yaml`, each justified in one sentence) and answers **allow / require_review / block**, with "would change if …". A **reversal guard** (Q-DEC-REV) speaks up when a PR puts back what the organisation decided once and later reversed: it names the superseded decision, the decision in force, and the evidence for the reversal (for the catalog's off-peak migrations: "off-peak migrations still lock the catalog"). It is advisory: it never changes the verdict or the risk, and it is the one thing that breaks the silence on `allow`. S6 (payment timeout 5000 ms, retries 0) → <!-- claim:s6.verdict -->block<!-- /claim --> (risk <!-- claim:s6.risk -->0.8<!-- /claim -->) with the ADR-012/013 links, the path to checkout and the owner team's reviewers. A GitHub Action for the demo app is in [`deploy/github-action/`](deploy/github-action/faultline-preflight.yml).

**Coordination (T2).** W-CLAIM-1 is an atomic conditional claim in one query. <!-- claim:s13.workers -->16<!-- /claim --> workers × <!-- claim:s13.rounds -->100<!-- /claim --> rounds gave <!-- claim:s13.rounds_one_owner -->100<!-- /claim --> rounds with exactly one owner and <!-- claim:s13.lost_updates -->0<!-- /claim --> lost updates. Read-only p95 was <!-- claim:s13.ro_p95_ms_during_writes -->9.462<!-- /claim --> ms during the write storm (measured on the pinned 6.0.2, not an engine guarantee).

**Contention on the real action path.** <!-- claim:contention.responders -->24<!-- /claim --> responders, each its own client, approve the same plan at the same moment: <!-- claim:contention.same.accepted -->1<!-- /claim --> approval is accepted and <!-- claim:contention.same.refused -->23<!-- /claim --> are refused at approval (the approval and the move to EXECUTE are one write), leaving <!-- claim:contention.same.intents -->1<!-- /claim --> intent, <!-- claim:contention.same.prs -->1<!-- /claim --> PR and <!-- claim:contention.same.operator_steps -->1<!-- /claim --> Operator step. When they race on <!-- claim:contention.diff.options -->3<!-- /claim --> different options at once, still <!-- claim:contention.diff.accepted -->1<!-- /claim --> approval lands (`evals/contention.py`).

</details>

</details>

## On-call: page, acknowledge, escalate, standing approval

Faultline runs the on-call loop itself, and every step is a FalkorDB node or a catalogue query ([API](docs/API.md#m19-on-call-pages-acknowledgements-escalation-standing-contracts-hand-offs), [graph model](docs/GRAPH_MODEL.md#m19-additions-on-call-pages-acks-escalation-standing-contracts-hand-offs)):

- **Page.** When an incident becomes approvable, the on-call person of the team that owns the failing component (`who_fixes`, read from the `ON_CALL` rota) and the on-call of every team that owns something in its blast radius (`Q-NOTIFY-1`) each get a `(:Page)`. Urgency comes from the obligation clock, and "unknown" counts as urgent. An incident the gate cannot route (escalated, or accepted without confidence) still pages the symptom owners' on-call.
- **Acknowledge.** With the page's signed link (HMAC over tenant and page id), the incident's run token or the approver key: `(:Person)-[:ACKED {at, via}]->(:Page)`. Telegram's Ack button does the same.
- **An approved fix that ends unresolved pages a human.** Verification UNKNOWN, a write-back not fully re-read, NOT_APPLIED or a fix not executed pages the people already paged and the approver at once, urgently; once per outcome, even when the reconciler settles the intent later.
- **Escalate.** A background tick reads `Q-PAGE-OVERDUE` and pages the next person of the incident's escalation order (`Q-PAGE-NEXT`, ranked in Cypher from the `algo.MSF` escalation tree). One write marks the late pages escalated and links them `ESCALATED_TO` the new page. Ack windows come from `weights.yaml` (urgent 5 min, normal 15).
- **Who may approve (a bug fixed).** `Q-APPROVER-1` described the approver as "on call" but only checked that the person was active. It now reads `ON_CALL`: the approver must be on call for, or in a team that owns, a component the incident impacts, and the approval states that reason; anyone else gets 403.
- **Standing approval ("handle it next time").** After a verified APPLIED fix, an eligible approver can grant a contract in two steps bound to a hash (family = the component the confirmed cause changed, the action, its parameters, a use limit and an expiry). On a later incident it applies only after the gate CONFIRMS a cause (G1–G8 unchanged) and the plan offers exactly that action. One guarded write (`uses < max_uses AND expires_at > now`, same family, action and parameters, grantor still active) consumes a use; the action then runs without waking anyone, verification still runs, and anything but APPLIED pages a human at once. A human can revoke it at any time.
- **Shift report, hand-offs and stats** (`Q-SHIFT-REPORT`, `(:Handoff)`, `Q-ONCALL-STATS`: MTTA, MTTR, people paged, handled under contract), also as read-only MCP tools (`oncall_now`, `pages`, `oncall_stats`). `POST /api/alerts` takes Alertmanager v4 or generic JSON and opens incidents through the same intake and run loop.
- **Who may be paged outside the app.** On the public demo, an anonymous run pages in-app only and never uses a standing contract; external channels are for keyed alerts and keyed runs, within an hourly budget per channel and a per-recipient cooldown. On-call state lives in its own graph (`oncall_<tenant>`), which re-arming the demo never touches.
- **Channels.** The in-app pager always; a Slack-compatible webhook, Telegram, PagerDuty Events v2 and email through AWS SES when configured. Standard library only, never blocking a run, the result recorded on the page.
- **One message per destination per incident wave.** Everyone one wave pages into the same Telegram chat gets ONE card listing them all (acknowledging stays per person: one button each in a shared chat, or the chat's own person's Ack); the webhook, PagerDuty and the email inbox get one message per wave with each person's own ack link. Each page still records its own delivery (`coalesced_into`), and the hourly budget counts messages, not pages. The channel, contract and report design is adapted from the author's own Beacon project.

**The Telegram on-call bot.** A page arrives as one phone-sized card, and the same message is edited in place as the incident moves (acknowledged by whom, escalated to whom, approved, APPLIED with the PR link, resolved, "fixed while you slept" under a contract). This is the hero incident's card from an S1 run, as the bot renders it:

```text
🔴 URGENT · inc-s1-m19tgcard
hero_bad_payment_deploy_with_same_minute_distractor
D-pay-417 caused this: D-pay-417 → payment → checkout
❌ Ruled out: D-email-88 (G5: cannot carry the impact); D-rec-12 (G2: no causal path)
⏳ slo-checkout breaches in ~605 min · 5 customer(s), 28,600 MRR at risk
👤 Why you: on call for team-payments, which owns payment (the failing component)
⏰ Ack by 13:34 UTC or it escalates
[Phone page] · [Incident room]
[✅ Acknowledge] [⏭ Escalate now] [🔎 Why] [🛠 Options] [👥 Who fixes] [📖 Runbook] [🔗 Open]
```

- **The bot is just another client.** Only Telegram users the operator maps to a person can act. Acknowledging is open to any mapped person. Choosing and approving run the web UI's own code: `Q-APPROVER-1`, the plan hash and the intent lease.
- **A tap never approves.** "Choose 1" shows the exact action and its plan hash; only the typed reply `approve <first 6 of the hash>` approves it, from the same person in the same chat, once, before the proposal expires. "yes" and "ok" are refused with the reason. Approval and acknowledgement record `via: telegram` and the Telegram user. Granting a contract after APPLIED (`grant …`) and revoking one (`revoke …`) are typed phrases too.
- **Commands:** `/start` (link the chat), `/oncall`, `/pages`, `/incident <id>`, `/ack <page>`, `/brain <question>` (the company brain, citations through its guard), `/report`, `/handoff <person> <note>`, `/contracts`, `/stats`, `/mute <minutes>` (holds back information notices; pages always ring), `/help`. An optional morning digest posts the shift report at a set hour.
- **Hardening:** the webhook secret is checked in constant time; every update is handled once (its `update_id` is claimed in the graph); per-chat rate limit; HTML escaped; every message within Telegram's 4096-character limit; a failed delivery is recorded on the page. The bot token is read in one function, never logged or returned (a test checks).
- **Setup:** `scripts/telegram_setup.py` registers the commands and description, sets the webhook with its secret, and verifies it with `getWebhookInfo` (idempotent).

| Server variable (`.env`, never committed) | What it does |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the bot's token (from @BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | the secret Telegram echoes on every update; without it the webhook refuses everything |
| `TELEGRAM_PEOPLE` | `tg_user_id:p-030,…`: the only users the bot acts for, each mapped to a person |
| `TELEGRAM_CHAT_ID` | optional shared on-call chat for pages to people who have not linked a chat with /start |
| `FAULTLINE_PUBLIC_URL` | https base for the webhook and the links in a card |
| `FAULTLINE_PAGE_SECRET` | key for the signed ack link in each card |
| `TELEGRAM_APPROVE_REAL` | `true` to allow approving against real GitHub from Telegram (default: web UI with the approver key) |
| `TELEGRAM_DIGEST_HOUR` | optional, 0–23 UTC: the morning digest |

**A scripted on-call night** (pre-registered, `make oncall-night`: the real API on clean rooms, the keyless investigator): <!-- claim:oncall.night.steps_passed -->14<!-- /claim --> of <!-- claim:oncall.night.steps -->14<!-- /claim --> steps passed. The first incident paged <!-- claim:oncall.night.inc1.people_woken -->5<!-- /claim --> people, escalated <!-- claim:oncall.night.escalations -->1<!-- /claim --> time when nobody acknowledged, stopped at the acknowledgement and was fixed on the on-call's approval. The same fault again paged <!-- claim:oncall.night.inc2.people_woken -->0<!-- /claim --> people (it sent <!-- claim:oncall.night.inc2.notices -->5<!-- /claim --> silent information notices) and was verified <!-- claim:oncall.night.inc2.verdict -->APPLIED<!-- /claim --> under the contract. The contract fired in <!-- claim:oncall.night.negatives_fired -->0<!-- /claim --> of <!-- claim:oncall.night.negatives -->5<!-- /claim --> negative cases (exhausted, revoked, expired, other parameters, the gate abstaining). MTTA read back from the graph (`Q-ONCALL-STATS`) equals the mean computed from the night's own pages (<!-- claim:oncall.night.mtta_matches_pages -->True<!-- /claim -->). The eval's clock is scripted, so these are correctness checks, not response-time claims; external channels were not configured (in-app only). This is run <!-- claim:oncall.night.runs -->5<!-- /claim -->: the earlier ones failed a harness check, predated "approval counts as the acknowledgement", read the numbers from every graph of the tenant, or predated the security review's fixes; all are kept on record, and no contract fired in a negative case in any of them (<!-- claim:oncall.night.runs_all_negatives_held -->True<!-- /claim -->).

## Learns from the people who use it (T2)

Faultline learns from recent work and from what its operators do, and all of it lives in FalkorDB: every trusted action is a `(:LearnEvent)` in the tenant's on-call graph, and what is learned is recomputed from those events by one Cypher query each, with recency decay written as an expression (`0.5 ^ (age / half-life)`, half-life in `weights.yaml learn`). Learning reorders, suggests and annotates. It never touches the gate, an approval rule or a contract's conditions, and every learned item names the events it came from ([API](docs/API.md#m21-what-faultline-learned), [graph model](docs/GRAPH_MODEL.md#m21-additions-learning-from-the-people-who-use-it)).

| Loop | What it learns from | Where it shows | What it may change |
|---|---|---|---|
| Choices | approvals and rejections per incident family and action kind → `(:Preference)` | PLAN (`learned_preferences`, `Q-LEARN-PREF`), with a why line | the order of options **within one predicted-future class**, blended with verified outcomes (`Q-REM-1`) |
| Guidelines | a rejection's reason → `(:Guideline {status: proposed})` | the next plan for that family and action, with who, when and which incident | nothing until a human promotes it; then the option is flagged and approving it needs an explicit override (stricter, never weaker); dismiss removes it |
| Responders | acknowledgements, approvals and verified fixes → `(:Person)-[:RESPONDED]->(component)` | ROUTE (`learned_responders`, `Q-LEARN-RESP`) | the person who answers is paged first, in addition to the rota (never instead of it) |
| Standing approvals | the same exact fix approved and verified on K incidents | the plan option | a suggestion to grant one; the grant is still the two-step M19 contract |
| Recent work | recall ranks look-alike incidents by similarity and recency (`Q-MEM-1`) | RECALL, the context pack ("last seen 3 days ago; fixed by …, verified") | which precedent comes first |
| Knowledge gaps | brain questions the graph could not answer → `(:KnowledgeGap)` | `GET /api/learned`, `knowledge_gaps` | a list of what to document, with the teams that own what each question was about |

**Public demo: visitors cannot poison it.** An action is learned only from a trusted actor: a run off the public demo or started with the approver key, a keyed alert, the approver key itself, or the operator-mapped Telegram bot (M19's trust rule). An anonymous visitor's approvals, rejections, acknowledgements and brain questions are never recorded, and changing or forgetting learned state needs the approver key there (`tests/live/test_learning_live.py`).

**Forget with a receipt.** `POST /api/learned/forget {person}` lists every event the person contributed and returns a receipt token; with the token and an approver it deletes exactly that set in one write, recomputes every preference, responder edge and gap it fed, writes a `ForgetReceipt` to the audit graph, and re-reads that nothing of theirs is left.

**Measured** (pre-registered, `evals/learning_night.py`: the real API on clean rooms, the keyless investigator; <!-- claim:learn.night.steps_passed -->13<!-- /claim --> of <!-- claim:learn.night.steps -->13<!-- /claim --> steps passed):

- **Choices, cold vs warm** (<!-- claim:learn.choices.scenarios -->S1,S1b<!-- /claim -->, three runs each): with nothing learned the top option was the rollback on both scenarios (the runs are deterministic, so the three per scenario are identical and count once); after the on-call approved the flag flip on <!-- claim:learn.choices.learning_plans -->5<!-- /claim --> incidents, the flag flip was first on both, with the line "<!-- claim:learn.choices.why_line -->learned: your team approved the flag flip 5 of the last 5 time(s) for payment; last just now<!-- /claim -->". The order changed on plan <!-- claim:learn.choices.flip_at_plan -->4<!-- /claim --> (after <!-- claim:learn.choices.pref_min_n -->3<!-- /claim --> choices), and the gate's verdicts were identical cold and warm.
- **Contract suggestion:** first shown on plan <!-- claim:learn.suggest.first_at_plan -->3<!-- /claim --> (after K = <!-- claim:learn.suggest.k -->2<!-- /claim --> verified approvals); shown before K <!-- claim:learn.suggest.before_k -->0<!-- /claim --> times.
- **Guidelines:** a rejection proposed one; promoted, it put the flag after the rollback and an approval without an override was refused (409); with the override it ran and was recorded; dismissed, it was gone.
- **Who responds:** a team member who answered every page while the on-call never did was paged in the first wave from incident <!-- claim:learn.routing.first_wave_from -->3<!-- /claim --> on; time to acknowledge went from <!-- claim:learn.routing.mtta_before_min -->16.0<!-- /claim --> to <!-- claim:learn.routing.mtta_after_min -->1.0<!-- /claim --> minutes, and the rota on-call was still paged every time (<!-- claim:learn.routing.oncall_paged_every_incident -->True<!-- /claim -->). The clock is scripted, so this checks the mechanism, not a real team's response time.
- **Forget:** forgetting the on-call's influence deleted <!-- claim:learn.forget.events -->14<!-- /claim --> events, left <!-- claim:learn.forget.events_left -->0<!-- /claim -->, and the next plan's top option went back to <!-- claim:learn.forget.top_after -->rollback_deploy<!-- /claim -->.
- **Recall:** the warm run's top precedent was the incident just resolved in <!-- claim:learn.recall.warm_top_first -->6<!-- /claim --> of <!-- claim:learn.recall.trials -->6<!-- /claim --> trials (<!-- claim:learn.recall.pairs -->S1->S1b,S3->S3b<!-- /claim -->), with gate verdicts identical in <!-- claim:learn.recall.gate_identical -->6<!-- /claim -->. On cold rooms, recency changed the top precedent in <!-- claim:learn.recall.top_changed -->3<!-- /claim --> of <!-- claim:learn.recall.scenarios_with_precedents -->3<!-- /claim --> scenarios that have precedents (on S1, from one <!-- claim:learn.recall.s1.w00.top_age_days -->92.5<!-- /claim --> days old to one <!-- claim:learn.recall.s1.w02.top_age_days -->2.5<!-- /claim --> days old).
- **Knowledge gaps:** <!-- claim:learn.gaps.count -->2<!-- /claim --> unanswered questions became gaps (one asked <!-- claim:learn.gaps.asked_max -->2<!-- /claim --> times); the answered and the off-topic question did not.

**T2 go/no-go** (the checklist we set before building it, `evals/t2_gonogo.py`): <!-- claim:t2.green -->5<!-- /claim --> of <!-- claim:t2.items -->5<!-- /claim --> green. Cold vs warm on two scenarios with three runs each (above); S13 concurrency <!-- claim:t2.s13.rounds_one_owner -->100<!-- /claim --> of <!-- claim:t2.s13.rounds -->100<!-- /claim --> rounds with exactly one owner and <!-- claim:t2.s13.lost_updates -->0<!-- /claim --> lost updates; S7 isolation <!-- claim:t2.s7.passed -->34<!-- /claim --> passed, <!-- claim:t2.s7.failed -->0<!-- /claim --> failed, also through the shipped read-only ACL users; S10 the forget receipt locally, and the live URL's read-only forget dry run answered <!-- claim:t2.s10.live_dry_run_status -->200<!-- /claim --> with a receipt token (an executed forget there would write the live audit graph, so it ran locally; the live URL serves learning: `GET /api/learned` <!-- claim:t2.s10.live_learned_status -->200<!-- /claim -->); session history: <!-- claim:t2.session.sessions -->2<!-- /claim --> sessions of one user, <!-- claim:t2.session.turns -->4<!-- /claim --> turns read back on a separate read-only connection.

## Screens

<table>
<tr>
<td valign="top"><img src="docs/screenshots/02-incident-room.png" alt="Incident room, verdict first: the cause and its proven graph path in one line, then the timeline, the failure-flow graph and the root cause"><br><sub><b>Incident room, verdict first.</b> One line says what caused it and by which graph path; each card names the FalkorDB query behind it ("via FalkorDB · algo.SPpaths · Q-GATE-1").</sub></td>
<td valign="top"><img src="docs/screenshots/03-naive-vs-faultline.png" alt="Naive recency ties two same-minute changes; the gate eliminates the look-alike by max flow and the decoy by no path"><br><sub><b>Naive vs the gate.</b> Recency ties the two same-minute deploys; the gate eliminates one by max flow (G5) and one by no path (G2).</sub></td>
</tr>
<tr>
<td valign="top"><img src="docs/screenshots/16-proof-story.png" alt="How it decides: a pinned proof graph follows the scroll, each step with the template Cypher that decides it"><br><sub><b>How it decides.</b> A pinned proof graph follows the scroll; each step shows the template Cypher that decides it.</sub></td>
<td valign="top"><img src="docs/screenshots/13-cypher-panel.png" alt="Cypher panel: every UI element opens the query that produced it"><br><sub><b>Cypher panel.</b> Every element on screen opens the query that produced it, with PROFILE and a read-only re-run.</sub></td>
</tr>
<tr>
<td valign="top"><img src="docs/screenshots/18-provenance.png" alt="Why do you believe this: the verdict's provenance, from the agents' calls to the evidence that supports it"><br><sub><b>Why do you believe this?</b> The verdict's provenance, from the agents' calls to the evidence that supports it.</sub></td>
<td valign="top"><img src="docs/screenshots/17-crew-board.png" alt="Crew board: every step of the run as a record in FalkorDB, who claimed it, what it ran and who it handed to"><br><sub><b>Crew board.</b> Every step of the run as a FalkorDB record: who claimed it, what it ran, who it handed to.</sub></td>
</tr>
<tr>
<td valign="top"><img src="docs/screenshots/19-preflight-reversal.png" alt="Preflight reversal guard: the PR puts back a decision the organisation reversed, with the evidence for the reversal"><br><sub><b>Preflight reversal guard.</b> The PR puts back a decision the organisation reversed, with the evidence for the reversal.</sub></td>
<td valign="top"><img src="docs/screenshots/20-brain-answer-graph.png" alt="A brain answer drawn as a graph: who decided, the decisions, and what they constrain"><br><sub><b>Company brain.</b> An answer drawn as a graph: who decided, the decisions, and what they constrain.</sub></td>
</tr>
</table>

<details><summary><b>More screens</b></summary>

| | |
|---|---|
| ![Home: the promise, the glossy cube that splits into the real graph, and the incident room below](docs/screenshots/01-home.png) | ![Obligations at risk: SLO burn, customers reached, ownership when the change shipped](docs/screenshots/14-obligations.png) |
| ![Preflight: a PR scored against the graph before it ships](docs/screenshots/10-preflight.png) | ![Company brain: answers cite node ids](docs/screenshots/07-brain.png) |
| ![Explore: the failure-flow graph in @falkordb/canvas](docs/screenshots/11-explore.png) | ![Tenant isolation: the brain on globex's own graph, with the isolation badge in the status panel](docs/screenshots/09-tenant-globex.png) |
| ![Where it sits: inputs, the per-tenant FalkorDB graph, the crew that proposes and the gate that decides, and what comes out](docs/screenshots/21-system-map.png) | ![Product tour: each tab is a real screenshot of a recorded run, with one callout on what matters](docs/screenshots/22-product-tour.png) |
| ![FalkorDB Browser: the proof path in the tenant graph](docs/media/falkordb-browser-path.png) | ![FalkorDB Browser: the decisions constraining payment](docs/media/falkordb-browser-decisions.png) |

<img src="docs/screenshots/15-mobile.png" width="300" alt="On a phone: the incident room opens on its verdict, with Verdict, Graph, Crew and Timeline tabs">

</details>

## Query catalogue

<!-- claim:repo.templates -->226<!-- /claim --> parameterised templates, one `.cypher` file per query id, linted for `LIMIT`, `ORDER BY`, bounded paths, a `CALL` allowlist and no writes. Cypher is never built from inputs. The full list with purposes and PROFILE timings: [docs/QUERY_CATALOGUE.md](docs/QUERY_CATALOGUE.md). Three of them, as stored:

<details><summary>Show the query catalogue</summary>


G5, the sufficiency bound ([`gate_flow.cypher`](backend/faultline/graph/templates/gate_flow.cypher)):

```cypher
// id: Q-GATE-3
MATCH (s:Node) WHERE s.id IN $sources
WITH collect(s) AS srcs
WHERE size(srcs) > 0
MATCH (t:Node {id:$symptom})
CALL {algo:maxflow}({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cap'}) YIELD maxFlow
RETURN maxFlow AS max_flow, size(srcs) AS sources
LIMIT 1
```

Containment, max flow over `cut_cost` with edge flows; the min-cut is computed from them in [`graph/algo/maxflow.py`](backend/faultline/graph/algo/maxflow.py) ([`cut_flow.cypher`](backend/faultline/graph/templates/cut_flow.cypher)):

```cypher
// id: Q-CUT-1
MATCH (f:Node {id:$failing})
MATCH (p:Node) WHERE p.id IN $protect
WITH f, collect(p) AS prot
WHERE size(prot) > 0
CALL {algo:maxflow}({sourceNodes: [f], targetNodes: prot, relationshipTypes: ['PROPAGATES_TO'], capacityProperty: 'cut_cost'}) YIELD edges, edgeFlows, maxFlow
RETURN [e IN edges | [startNode(e).id, endNode(e).id]] AS flow_edges, edgeFlows AS flows, maxFlow AS max_flow
LIMIT 1
```

The citation guard: the brain may cite only ids a tool call of this run actually saw ([`cite_check.cypher`](backend/faultline/graph/templates/cite_check.cypher)):

```cypher
// id: Q-CITE-1
MATCH (run:Run {id:$run})-[:HAS_TOOL_CALL]->(:ToolCall)-[:SAW]->(n:Node)
WHERE n.id IN $ids
RETURN collect(DISTINCT n.id) AS seen
LIMIT 1
```

</details>

## Safety

The full table (agent cannot … | enforced by | file::function | test) is in [docs/SAFETY.md](docs/SAFETY.md); the public-demo threat model is in [SECURITY.md](SECURITY.md).

<details><summary>Show the safety envelope in detail</summary>


- **Reads.** `GRAPH.RO_QUERY` only, with a per-query `TIMEOUT` (clamped to `TIMEOUT_MAX`) and a literal `LIMIT` sent as n+1 so truncation is detected. They run as a per-tenant ACL user (`ro_<tenant>`) when ACL passwords are configured, as the production compose does; local keyless runs use the default user. The model never holds a write connection.
- **Templates first.** Text2cypher is the last resort and passes three layers: a guard on the masked text, a `GRAPH.EXPLAIN` plan check, and `RO_QUERY` as the read-only user with a short timeout.
- **Two-step approval.** Choosing an option ≠ approving it. Approval must quote the plan hash of the exact rendered action (file diff, commit message, PR body with reviewers, rollback), and it moves the incident to EXECUTE in the same query. Execute re-checks the intent owner, the plan hash and drift at GitHub main, and refuses no-op changes.
- **Three-valued verification.** Channel 1 re-reads GitHub main (simulated GitHub in keyless mode). Channel 2 reads the world's telemetry after the change for every symptom, plus collateral on what was protected. In this demo, telemetry comes from the simulator, which reads the same graph: the two channels are separate checks, not independent physical sensors. `UNKNOWN` goes to a human and never writes success. A failed fix goes back to approval with that option disabled.
- **Cross-system honesty.** intent → execute → reconcile with an idempotency key; no claim of cross-system transactions. A reconciler settles PENDING intents after crashes or timeouts, at API start and every minute, taking over the intent lease of a process whose heartbeat stopped. With real GitHub, approval requires an approver key.
- **Tenancy.** One graph per tenant; clean rooms via `GRAPH.COPY`. The hosted MCP binds a bearer key to one tenant and hosts no tool that writes.

| Failure mode | Defence | Proof |
|---|---|---|
| The model names a plausible but wrong change | G2: no causal path, no claim | `D-rec-12` rejected (S1); `test_algo_load_bearing.py::test_sppaths_decides_g2` |
| A look-alike has a path too | G5 max flow; origin test (a suspect whose own component was measured healthy is not the origin); G4 upstream | `D-email-88`, `D-fx-pause-7`; arm A3-noG5 |
| The model cites something it never read | G1 (agent) and Q-CITE-1 (brain): every cited id ⊆ ids the run's own tool calls returned | `tests/brain/test_citation_guard.py`, `tests/llm/` |
| An incident is invented | three-valued no-incident: measurements normal plus an `algo.SSpaths` negative proof | S4D, S4S |
| An innocent deploy sits downstream of what really broke | G4 upstream eliminates it; with no change upstream, the run abstains | deep bench `abstain_downstream`; `tests/live/test_gate_upstream.py`; mutant `M-G4-UPSTREAM` |
| Missing telemetry looks like "nothing wrong" | N0: every alerting symptom must itself be measured before "no incident" is accepted | robustness eval; `tests/live/test_negative_proof_missing.py`; mutant `M-N0-UNMEASURED` |
| Wrong action, or the wrong action approved | plan hash binds the exact diff; exclusive approval; drift guard | `tests/live/test_actions.py` |
| A fix that didn't take is reported as success | three-valued verify; NOT_APPLIED goes back to approval; UNKNOWN never writes success | S5, S9 |
| A crash between GitHub and the graph | intent → execute → reconcile by idempotency key | `test_reconciler_*`; chaos eval |
| One tenant sees another's data | graph per tenant, RO wrapper ownership check, ACL user, guard | S7 |

</details>

## What's real vs synthetic

- **Real:** FalkorDB and every query and algorithm; the agent loop; the gate; the existing data pipeline (DuckDB warehouse plus invariant suite), whose rebuild verifies data repairs.
- **Exercised against real GitHub once, on the hero scenario:** with `FAULTLINE_GITHUB=real`, S1 opened, merged and verified [PR #1 on faultline-demo-infra](https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1) (`paymentGate` off, verdict APPLIED, the plan hash's idempotency key in the PR body). The live demo and every eval run use the simulated GitHub, so visitors never touch a real repo.
- **Synthetic, seeded and deterministic:** the org, history, ADRs and runbooks; service telemetry, from a share-weighted simulator that writes `MetricWindow` nodes the agent reads only through templates; the OpenTelemetry-Demo-shaped topology.
- **Real, once, as a benchmark:** FaultBench-OTel ran the real OpenTelemetry Demo with its own fault flags and fed Faultline the demo's measured error rates ([details](docs/EVALS.md#faultbench-otel-a-real-system-real-telemetry-pre-registered-2026-10-16)); the decoy changes and the page rule are ours.
- **Keyless mode** uses a simulated GitHub, labelled "simulated" on every result.

Pointing this at a real stack: [docs/REAL_STACK.md](docs/REAL_STACK.md).

## Honest limits

The full list, each with its source: [docs/HONEST_LIMITS.md](docs/HONEST_LIMITS.md).

- The deterministic investigator measures what the graph says can be measured. The LLM investigator (`LLMInvestigator`) was measured only in a small comparison (one model; A0 and A1 three trials per scenario, A3L one per scenario on all 8, one trial per world on the adversarial benches); every other number uses the deterministic one.
- Data repairs need a proposed transform patch. Keyless runs cannot author SQL, so the option is shown disabled rather than faked.
- Config facts are extracted deterministically from JSON/YAML diffs. Facts hidden in code diffs need the LLM extractor.
- Warm memory did not reduce tool calls for the deterministic investigator (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim -->). Its effect is ordering, runbooks and the plan.
- The concurrency numbers are measurements on one machine. FalkorDB 6.0 serialises writes per graph; we do not claim engine-level MVCC. <!-- noclaim: engine version -->
- The capacities are modelled from criticality and row share, not learned from traffic, and the gate assumes a single cause by default (joint sufficiency is reported as "not confident").
- The preflight backtest is weak on acme (see Results), and its thresholds flag too many PRs. Historical PRs carry no ChangeFacts, so the decision term never fired in the backtest, and chokepoint scores and decisions are read as they are now (the topology itself is versioned: `valid_from` on calls, `topology_at` answers "what could this break back then?").
- Learned remediation ordering counts a NOT_APPLIED rollback of the wrong change as a rollback failure, and it is not conditioned on the kind of cause. In the seeded tenants its success rates come from the synthetic history's per-family fix lists, so they show the mechanism, not real-world rates. It can put a broader action (a rollback) above the min-cut's smaller one (a flag); both stay offered, each with its reason.
- Telegram: no voice notes (Beacon's speech-to-text is not ported), one linked chat per person, and the bot answers one tenant (`FAULTLINE_TENANT`). Approving against real GitHub from Telegram is off unless the operator sets `TELEGRAM_APPROVE_REAL`.
- On-call: each external channel delivers to one shared destination (one webhook, one Telegram chat, one PagerDuty service, one SES list) and names the person paged; there is no per-person contact routing yet. Every team that owns something in the blast radius is paged, which is several people for the hero incident. Alert intake reads only the telemetry the graph holds: with none (no live metrics ingest is wired to it), an alert escalates to a human rather than being diagnosed. Contracts cover `flip_flag` and `rollback_deploy` only.
- Hidden-coupling findings come from co-failure in synthetic incident history. They are suggestions for a human to confirm, never evidence for the gate.

## What didn't work

The items from the scenario and bench runs are also generated by the eval run ([evals/RESULTS.md](evals/RESULTS.md), "What didn't work"); the rest come from the side benches named in each.

- **Recall memory does not change the answer on the scenarios.** Memory off (A2) and on (A3) reach the same root causes (top-1 <!-- claim:arm.A2.top1 -->1.0<!-- /claim --> vs <!-- claim:arm.A3.top1 -->1.0<!-- /claim -->): the gate decides from fresh evidence, so recalled precedents change order, runbooks and the plan, not the verdict. What does change the verdict is the graph learning from a verified fix (see Results).
- **Warm memory did not save work.** The deterministic investigator measures every suspect anyway (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim --> tool calls). Nor can S1b show a reordering effect: it has <!-- claim:memory.suspects -->1<!-- /claim --> suspect, so the true cause ranks <!-- claim:memory.cold_true_cause_rank -->1<!-- /claim --> cold and <!-- claim:memory.warm_true_cause_rank -->1<!-- /claim --> warm by construction; a fair test of memory's ordering needs a repeat incident with rivals, which we have not built.
- **Our adversarial bench caught a safety hole, and an independent review caught our first fix.** The deep bench put deploys *downstream* of what broke, a pattern no earlier bench generated: the shipped gate confidently blamed an innocent deploy below an unchanged break in 16 of 20 worlds. Our first fix (an upper-bound "upstream explains it" rule) found every cause, but a reviewer built worlds where it blamed the wrong change (35 in 80). The redesign eliminates only under a strict lower bound and holds at <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> confident wrong blames in <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> fresh worlds, at the price of abstaining on part of the look-alike cases. Earlier "0 wrong-confident" numbers were true but bounded by what our benches generated. <!-- noclaim: 16 of 20 and 35 in 80 are pre-fix runs -->
- **Preflight is noisy on history.** On acme it flags <!-- claim:backtest.acme.full.all.flag_rate -->0.6525<!-- /claim --> of all past PRs and ranks the causing ones no better than chance (AUROC <!-- claim:backtest.acme.full.all.auroc -->0.5179<!-- /claim -->). The pre-registered thresholds were not re-tuned.
- **Missing telemetry is the weak spot, and it hid a bug.** With error-rate windows deleted for a fifth of components, correct verdicts on the second-seed gate-bench worlds drop from <!-- claim:robustness.baseline.correct -->100<!-- /claim --> to <!-- claim:robustness.missing.0.2.correct -->83<!-- /claim -->. The first run of this eval also caught Faultline calling three real faults "no incident" because the symptom's own data was gone; the gate now requires every alerting symptom to be measured (N0), and every lost case abstains.
- **Our prediction about the ladder was wrong.** We pre-registered that removing `algo.SPpaths` or `algo.maxFlow` would produce wrong confident blames; it produced none (<!-- claim:ladder.neither.wrong_confident -->0<!-- /claim -->). Our first write-up then over-read the strict grade as lost answers: with one algorithm removed the right cause is still blamed in every world that has one, because the other algorithm eliminates the decoys. Only removing both loses causes (<!-- claim:ladder.neither.b.abstained_not_correct -->22<!-- /claim -->, all to abstention).
- **A sensible heuristic nearly matches us on our own scenarios.** Telemetry with a floor (T+: blame the most anomalous changed component, or say "none" when nothing is above one percentage point) gets <!-- claim:seeds.scen.Tplus.outcome_correct.k -->26<!-- /claim --> of <!-- claim:seeds.scen.Tplus.outcome_correct.n -->32<!-- /claim --> seeded scenario worlds right with <!-- claim:seeds.scen.Tplus.wrong_blame.k -->0<!-- /claim --> wrong blames, against <!-- claim:seeds.scen.A3.outcome_correct.k -->32<!-- /claim --> of <!-- claim:seeds.scen.A3.outcome_correct.n -->32<!-- /claim --> for Faultline. Its misses are the data incident (no error-rate telemetry on tables) and naming the inferred origin on S12. The hand-written scenarios are where the gate was developed; the generated benches, with look-alikes that are themselves anomalous, are where the graph has to earn its place.
- **Small faults are missed.** Scaled down to a few percentage points of error rate, faults fall under the gate's one-point floor and it declares "no incident" while the alert fires (<!-- claim:curve.effect.0.025.correct -->15<!-- /claim --> of 100 correct at the smallest size tested). A missed incident, not a wrong blame, but a miss.
- **Some abstentions name the wrong suspect.** A run can end "not confident" with a suspect attached; on the deep bench <!-- claim:deep.fresh.accepted_nc.bystander -->9<!-- /claim --> (headline) and <!-- claim:seeds.deep.accepted_nc.bystander -->24<!-- /claim --> (new seeds) of those suspects were innocent changes, all below an unchanged break. Nothing is acted on without approval, but the human is shown the wrong suspect.
- **The company brain is still sensitive to wording.** Rewording each of its <!-- claim:brain.questions -->33<!-- /claim --> questions drops it from <!-- claim:brain.correct -->33<!-- /claim --> to <!-- claim:brain_para.correct -->30<!-- /claim --> correct, and that reworded set is the one its router was built on, so it is not blind. Routing is two-stage: keyword patterns decide when one matches; otherwise a question is matched against seeded examples of each question kind in FalkorDB (vector + full-text, fused in one query) or refused. The misses are questions that read like another kind (a decision question phrased like knowledge decay, an overview that names people). On questions nobody tuned against it does worse: <!-- claim:brain_blind.s2.hybrid.correct -->24<!-- /claim -->/<!-- claim:brain_blind.s2.hybrid.questions -->40<!-- /claim --> on a blind set written by an agent that never saw the router (<!-- claim:brain_blind.s2.keyword_router.correct -->19<!-- /claim -->/<!-- claim:brain_blind.s2.keyword_router.questions -->40<!-- /claim --> with keywords alone). A first, graph-only router scored 29/33 on the development set but did not beat keywords on the first blind set (23/40 against 25/40), so it became the fallback stage instead. <!-- noclaim: set-1 counts are in evals/results/brain_heldout.json and RESULTS.md (brain_blind.s1.*) -->
- **A pre-registered eval was dropped.** The procedural-memory eval (warm runs should need at least 30 % fewer tool calls) was never run; the cold/warm check shows <!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim --> tool calls.
- **On the second tenant the graph did not beat a good heuristic.** On <!-- claim:world_globex.cases -->200<!-- /claim --> globex worlds with look-alikes placed uniformly, Faultline was right <!-- claim:world_globex.right_cause -->106<!-- /claim --> times with <!-- claim:world_globex.wrong_confident -->0<!-- /claim --> confident wrong blames; thresholded telemetry was right <!-- claim:world_globex.Tplus.right_strict -->107<!-- /claim --> times with <!-- claim:world_globex.Tplus.wrong_any -->1<!-- /claim -->. The graph pays off where look-alikes are themselves anomalous (deep and decisive benches), not when they are mostly healthy.
- **The telemetry simulator silently dropped edges.** Enabling globex showed that its one-read topology view lost the failure edges of batch jobs with no callers, so those jobs never saw upstream faults in the simulated world. The paged read keeps them; acme has no such job, so its worlds and numbers are unchanged. <!-- noclaim: description -->
- **FalkorDB's own GraphRAG-SDK beat the company brain on blind wording.** On the pre-registered blind set the SDK answered <!-- claim:graphrag.s2.sdk.correct -->32<!-- /claim -->/<!-- claim:graphrag.s2.questions -->40<!-- /claim --> against the brain's <!-- claim:graphrag.s2.fl.correct -->24<!-- /claim -->; we had predicted 12 to 22 for the SDK. The brain's misses are wordings its router sends to the wrong template ([GraphRAG-SDK arm](docs/EVALS.md#company-brain-vs-falkordbs-graphrag-sdk-pre-registered-2026-10-17)).
- **Real telemetry found a bug the simulator hid.** On the first real-system window (FaultBench-OTel, the OpenTelemetry Demo) Faultline said "no incident" while a service was failing: healthy real services report exactly zero errors, which the simulator never produces, and the measurement rule could not call a rise from zero anomalous. As registered, the product got <!-- claim:otel.faultline_prefix.right_cause.k -->0<!-- /claim --> causes right and called <!-- claim:otel.faultline_prefix.no_incident_fault -->15<!-- /claim --> real faults "no incident"; both versions are reported. On the same bench it also abstained where a fault hangs instead of failing (errors only at the edge proxy), something an error-rate-only product cannot place.
- **Our first LLM comparison had two flaws** (S12 unanswerable by the prompt, the data control without warehouse evidence); see [Results](#results).
- **Self-authored data.** All scenarios, history and brain questions are synthetic and ours. The 3 trials per scenario of `make eval` are identical copies (deterministic investigator), so the scenario suite counts as 8 cases; the world-seed run (5 telemetry seeds per scenario) adds real variation.

## Existing system and what was built here

Faultline grew out of an earlier data-incident agent: a DuckDB pipeline with an invariant suite and a repair-PR step. It used DataHub for lineage and write-back. DataHub has been removed completely. The pipeline and invariants are kept as the *system under observation* and as the data-repair verifier.

The FalkorDB graph and everything built on it is new: tenants, templates and algorithms; the gate, agent loop and MCP server; actions and verification; memory, brain, preflight and coordination; the UI incident room.

## AI disclosure

Built with Claude Code (Anthropic) as the coding agent, under a written plan and project rules kept by the author. The product's own LLM investigator uses Anthropic models (`claude-opus-5-5`, `claude-sonnet-5-5`) when a key is configured; every keyless path is deterministic. Decisions, numbers and gate verdicts come from code and FalkorDB, never from the model.

## Repo map

`backend/faultline/` holds the graph layer (`graph/`: RO wrapper, writes, templates, `algo/`, guard, tenancy), the agent (`agent/`: loop, gate, score, phases, crew), `mcp_server/`, `actions/`, `memory/`, `brain/`, `preflight/`, `sim/`, `ingest/` and `api.py`. `frontend/` is the Next.js UI, `evals/` the harness and benches, `tests/` the unit and live suites. Full map: [docs/REPO_MAP.md](docs/REPO_MAP.md).

## Team

Prashant ([@Prashant-thakur77](https://github.com/Prashant-thakur77)), solo build, with Claude Code as the coding agent (see AI disclosure).

## License

Apache-2.0 ([LICENSE](LICENSE)). The OpenTelemetry Demo topology it models is Apache-2.0; all organisational data is synthetic.
