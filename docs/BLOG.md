# Our on-call agent isn't allowed to blame a deploy until FalkorDB returns a path

*Draft for dev.to / Hashnode. Not published yet. Every measured number below is checked against `evals/results/latest.json` by `make claims`.*

## Two deploys, one minute

It's the middle of the night. Checkout errors spike. Two deploys shipped in the same minute: one to the payment service and one to the email service. A third change, a recommendation cache tweak, went out a minute earlier.

A similarity search has nothing to separate them: both are in the right time window and both sit near checkout. We measured it: ranking the changes by how close their descriptions' embeddings are to the incident's (cosine, inside FalkorDB) gets top-1 <!-- claim:arm.V.top1 -->0.4<!-- /claim --> across our scenarios. Pick the most recent change, the classic heuristic, and you do worse: top-1 <!-- claim:arm.N.top1 -->0.1<!-- /claim -->, counting ties as a fraction.

A strong language model does better than either, and we measured that too. Given the alert, per-minute telemetry, the change list and, for data incidents, the warehouse evidence, `claude-opus-5-5` got the right verdict in <!-- claim:arm.A0.outcome_correct.k -->23<!-- /claim --> of <!-- claim:arm.A0.outcome_correct.n -->24<!-- /claim --> trials across our 8 scenarios and never blamed an innocent change. On scenarios like ours, a capable model with good evidence is as accurate as our gate. So the gate is not there to be smarter than the model. It is there so the answer is a proof anyone can re-run, costs no tokens and comes out the same every time, before an agent opens a pull request against production. (Our first version of this test was unfair to the model in two ways; the numbers here are from the fixed rerun.)

We built **Faultline**, an on-call agent with one rule: **no path, no claim.** It may not name a root cause until FalkorDB returns a causal path from the change to the symptom. The model can suggest; a read-only query decides.

## Why a graph, and which graph

Incidents cross boundaries that no single tool sees. A payment provider cutover is a *service* change. Its blast radius runs through a raw table, two transforms, a revenue mart and an executive KPI, which is *data lineage*. The fix belongs to whoever wrote that code and fixed the last outage there, which is *people*. And it may violate a decision the team already wrote down, which is *ADRs*.

In Faultline those live in one per-tenant FalkorDB graph:
- **Topology.** Services, datastores and feature flags. `PROPAGATES_TO` edges carry a capacity: how much of a failure flows downstream. A synchronous call has capacity 1.0; a best-effort email call has 0.02. <!-- noclaim: configured capacity -->
- **Data lineage.** Tables, transforms and KPIs. Here the capacity is the end-to-end row share.
- **Changes.** Deploys that `CHANGED` components, and PRs that `TOUCHES` files.
- **People.** Ownership, on-call windows, commits, collaboration.
- **Knowledge.** Decisions (`SUPERSEDES`, `CONSTRAINS`), runbooks, postmortems, and past incidents with vectors.

## The gate: a path is necessary, not sufficient

The load-bearing query is `algo.SPpaths` from the change to the symptom:

```cypher
MATCH (c:Node {id:$cause}), (s:Node {id:$symptom})
CALL algo.SPpaths({sourceNode: c, targetNode: s, relTypes: ['CHANGED','GATES','PROPAGATES_TO'],
                   weightProp: 'w', relDirection: 'outgoing', maxLen: 8, pathCount: 3}) YIELD path, pathWeight
RETURN [n IN nodes(path) | n.id] AS chain, pathWeight AS weight
ORDER BY weight LIMIT 3
```

The recommendation tweak has no path to checkout, so it is rejected (G2). But the email deploy *does* have one: checkout calls email to send the confirmation. This is where most "graph RAG" stops, and where ours keeps going.

We run `algo.maxFlow` from the suspect to the symptom over those capacities. The email path can carry at most <!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim --> of checkout's traffic, but we need <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim --> to explain what we see: the observed share <!-- claim:s1.D-email-88.observed -->0.3041<!-- /claim -->, with slack for noise. Rejected (G5), with the Cypher and the numbers attached. The payment deploy passes every check, and the proof path is <!-- claim:s1.chain -->D-pay-417 → payment → checkout<!-- /claim -->.

The same gate works on the data incident. A stale FX feed *does* reach the revenue KPI, but it touches a small share of rows: max flow <!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> against <!-- claim:s2.D-fx-pause-7.needed -->0.8<!-- /claim --> needed. The payment cutover's path crosses from a service into the lineage: <!-- claim:s2.chain -->D-cutover-1 → payment → raw.raw_orders → staging.stg_orders → marts.fct_revenue → marts.exec_revenue_metric → kpi.exec_revenue<!-- /claim -->.

Gate v2 has eight checks:
- grounded;
- path;
- time;
- quantitative;
- flow;
- competitors;
- two-channel agreement;
- decision contradiction.

Each one is a read-only query plus arithmetic in code, never a model judgement.

## Ten algorithms, each changing a decision

We gave ourselves a test: if an algorithm's answer can change without a decision changing, it's decoration. `tests/live/test_algo_load_bearing.py` perturbs, on a `GRAPH.COPY` clean room, exactly what each algorithm reads, and asserts that the decision flips:

| Algorithm | Decision |
|---|---|
| BFS | blast radius |
| SPpaths | the gate's path check |
| SSpaths | the no-incident negative proof |
| maxFlow | sufficiency, and the containment min-cut |
| WCC | whether a cut is needed at all |
| betweenness | preflight risk |
| pageRank | investigation order |
| HarmonicCentrality | who gets paged |
| MSF | the escalation tree |
| labelPropagation | which incidents form a family, and therefore which runbook gets derived |

## The model never holds a write connection

- **Reads.** Every read is `GRAPH.RO_QUERY` with a timeout and a `LIMIT`, as a per-tenant read-only ACL user.
- **Writes.** Writes are single atomic queries in one module.
- **Actions.** Choosing an option is not approving it: you approve the exact rendered change by its plan hash. Approval moves the incident out of the approvable state in the same query, so it can't race.
- **Verification is three-valued.**
  - First channel: GitHub main is re-read.
  - Second channel: telemetry after the change, checked for every symptom and for collateral on what was protected.
  - An `UNKNOWN` goes to a human, and a reconciler settles it later by the idempotency key.
- **Write-back.** The write-back is re-read through a separate connection: <!-- claim:s1.writeback -->7/7<!-- /claim --> on the hero run.

## Memory that reorders but never decides

**Recall.**
- Recall seeds from the incident's own vector in FalkorDB's index, then requires a shared `Symptom` node.
- Families come from `algo.labelPropagation`. When a family has two or more incidents fixed the same verified way, it becomes a derived runbook with provenance.

**What it measured.** On a repeat payment regression:
- the warm run's top precedent was the incident we had just resolved;
- the derived runbook came first;
- the prior on the right component rose from <!-- claim:memory.cold_prior -->0.7681<!-- /claim --> to <!-- claim:memory.warm_prior -->0.8423<!-- /claim -->;
- the gate's verdicts were identical cold and warm (<!-- claim:memory.gate_verdicts_identical -->True<!-- /claim -->). That is exactly what we want: memory may reorder the investigation, but the gate decides from fresh evidence.

**What didn't work.** We expected warm memory to cut the number of tool calls. For our deterministic investigator it didn't (<!-- claim:memory.cold_tool_calls -->17<!-- /claim --> → <!-- claim:memory.warm_tool_calls -->17<!-- /claim -->), because it measures every suspect anyway.

## The ablation

With FalkorDB switched off, the same agent confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes: every read goes through FalkorDB, so it fails closed by design. That is a property check, not a measurement. The measured ablation is the capability ladder: remove both the path check (`algo.SPpaths`) and the flow check (`algo.maxFlow`) and the right cause is blamed in <!-- claim:ladder.neither.b.right_cause -->43<!-- /claim --> of <!-- claim:ladder.neither.b.confirm_cases -->65<!-- /claim --> generated worlds instead of <!-- claim:ladder.full.b.right_cause -->65<!-- /claim -->; remove only one and the other covers for it. On our <!-- claim:arm.A3.scen.n -->8<!-- /claim --> hand-written scenarios, which are also the set the gate was developed on, the product gets <!-- claim:arm.A3.scen.outcome_correct_strict.k -->8<!-- /claim --> right with no wrong blame; with only 8 cases that bounds the true rate at no less than about <!-- claim:arm.A3.scen.outcome_correct_strict.ci_lo -->68%<!-- /claim --> (95 % interval). The numbers that carry weight are the generated benches below.

These are keyless runs with a deterministic investigator. We also ran the same model three ways, three trials per scenario: alone (<!-- claim:arm.A0.outcome_correct.k -->23<!-- /claim --> of <!-- claim:arm.A0.outcome_correct.n -->24<!-- /claim --> right), with vector-RAG over our runbooks, postmortems and ADRs (<!-- claim:arm.A1.outcome_correct.k -->23<!-- /claim --> of <!-- claim:arm.A1.outcome_correct.n -->24<!-- /claim -->), and as Faultline's investigator with the graph gate deciding (<!-- claim:arm.A3L.outcome_correct.k -->8<!-- /claim --> of <!-- claim:arm.A3L.outcome_correct.n -->8<!-- /claim -->, one trial each). The gate decides the same way whichever investigator proposes, so A3L shows that the model drives the tools without breaking the loop; it costs a median <!-- claim:arm.A3L.tokens_median -->38353<!-- /claim --> tokens per incident against <!-- claim:arm.A0.tokens_median -->2522<!-- /claim --> for the model alone, which is the price of gathering its own evidence.

## The trade we chose: recall for safety

The bench that matters most is the one we built to break the gate: <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> generated worlds with the cause up to four hops upstream, look-alike deploys on the path and on the alerting service, and five adversarial kinds. The comparison is a telemetry heuristic that blames the most anomalous changed component. That heuristic is strong in our simulator, because the cause usually has the largest error rise.

| Same <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds | Right cause (of <!-- claim:deep.fresh.all.cause_cases -->100<!-- /claim --> with one) | Confident wrong blames | Abstained |
|---|---|---|---|
| Faultline | <!-- claim:deep.fresh.all.right_cause -->51<!-- /claim --> | <!-- claim:deep.fresh.all.wrong_confident -->0<!-- /claim --> | <!-- claim:deep.fresh.all.abstained -->89<!-- /claim --> |
| Telemetry heuristic | <!-- claim:deep.fresh.all.T.right_strict -->85<!-- /claim --> | <!-- claim:deep.fresh.all.T.wrong_any -->55<!-- /claim --> | <!-- claim:deep.fresh.all.T.abstained -->0<!-- /claim --> |

The heuristic finds more causes, and it blames an innocent deploy in <!-- claim:deep.fresh.all.T.wrong_any -->55<!-- /claim --> worlds. Faultline finds fewer and blames nobody it cannot prove, so it hands the rest to a human. On <!-- claim:seeds.deep.cases -->420<!-- /claim --> more worlds from seeds generated for the first time in our numbers audit, the pattern held: <!-- claim:seeds.deep.right_cause -->136<!-- /claim --> right, <!-- claim:seeds.deep.wrong_confident -->0<!-- /claim --> confidently wrong. Two honest caveats:
- **Not every abstention is clean.** In <!-- claim:deep.fresh.accepted_nc.bystander -->9<!-- /claim --> of the <!-- claim:deep.fresh.all.cases -->140<!-- /claim --> worlds the gate ended "not confident" while naming an innocent change as its suspect.
- **On our hand-written scenarios, the gap is small.** A version of the heuristic that may also say "none" matched most of them; the graph earns its place where look-alikes are themselves anomalous. Where the look-alike has a fault of its own, removing `algo.maxFlow` takes the right answers from <!-- claim:decisive.full.g5_only.right_cause -->20<!-- /claim --> of <!-- claim:decisive.full.g5_only.cases -->20<!-- /claim --> to <!-- claim:decisive.no_maxflow.g5_only.right_cause -->0<!-- /claim -->.

## It runs, on a real deployment and a real repository

The demo is live, and we measured it from outside over HTTPS: the hero incident, run end to end <!-- claim:live.hero.n -->5<!-- /claim --> times, found the right cause <!-- claim:live.hero.cause_correct -->5<!-- /claim --> times and was verified APPLIED <!-- claim:live.hero.applied -->5<!-- /claim --> times, with a p50 of <!-- claim:live.hero.verdict_ms_p50 -->1584.4<!-- /claim --> ms from alert to verdict. With the real GitHub client switched on, the same flow opens, merges and verifies an actual pull request: the flag flips at `main` of a demo infrastructure repository, and the verdict is APPLIED only after `main` is re-read.

## FalkorDB notes from the trenches

We pinned 6.0.2 by digest after running our engine smoke suite on both candidate versions. A few things we learned the hard way, each reduced to a minimal reproduction and checked against FalkorDB's issue tracker before filing:
- `SSpaths`' `pathCount` is a global top-k, so a full result means "possibly truncated".
- An `OPTIONAL MATCH` after an aggregating `WITH` returned no rows.
- Aggregating `SSpaths` output together with a null property crashed the whole server, from a read-only query. It turned out to be a known bug; we added a smaller repro and two more triggers to [the thread](https://github.com/FalkorDB/FalkorDB/issues/3150). We aggregate per node first.
- `algo.WCC` and `algo.pageRank` fail when the projected label set holds exactly one node, which happens naturally when a time window holds a single alert. Filed as [FalkorDB#3349](https://github.com/FalkorDB/FalkorDB/issues/3349); we add an anchor node until it is fixed.

## Try it

- The live demo: [13-203-185-119.sslip.io](https://13-203-185-119.sslip.io) (keyless; press Re-arm to reset it).
- The code: [github.com/Prashant-thakur77/Faultline](https://github.com/Prashant-thakur77/Faultline). `make setup && make judge-check` runs every check offline, with no API key, and prints PASS.
- Every number in one place: [docs/PROOF.md](https://github.com/Prashant-thakur77/Faultline/blob/main/docs/PROOF.md).
- Point your own agent at the hosted read-only MCP tools with the public demo key in [docs/MCP.md](https://github.com/Prashant-thakur77/Faultline/blob/main/docs/MCP.md), and ask for `causal_paths` from `recommendation` to `checkout`: no path, so no claim.
