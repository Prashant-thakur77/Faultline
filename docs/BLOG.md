# Our on-call agent isn't allowed to blame a deploy until FalkorDB returns a path

*Draft for dev.to / Hashnode. Not published yet. Every measured number below is checked against `evals/results/latest.json` by `make claims`.*

## Two deploys, one minute

It's the middle of the night. Checkout errors spike. Two deploys shipped in the same minute: one to the payment service and one to the email service. A third change, a recommendation cache tweak, went out a minute earlier.

A language model asked which one did it will happily write a confident paragraph. A similarity search has nothing to separate them either: both are in the right time window and both sit near checkout. We measured the similarity part: ranking the changes by how close their descriptions' embeddings are to the incident's (cosine, inside FalkorDB) gets top-1 <!-- claim:arm.V.top1 -->0.4<!-- /claim --> across our scenarios. (We have not run an LLM-only arm.) Pick the most recent change, the classic heuristic, and you do worse: top-1 <!-- claim:arm.N.top1 -->0.1<!-- /claim -->, counting ties as a fraction.

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

With FalkorDB switched off, the same agent confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes. It refuses rather than guesses. With the graph, top-1 is <!-- claim:arm.A3.top1 -->1.0<!-- /claim --> on our scenarios, with zero false blame and correct abstention on both controls.

These are keyless runs with a deterministic investigator. We have not yet run the LLM-only and vector-RAG arms, so we make no claim about them.

## FalkorDB notes from the trenches

We pinned 6.0.2 by digest after running our engine smoke suite on both candidate versions. A few things we learned the hard way, all drafted as upstream issues:
- `SSpaths`' `pathCount` is a global top-k, so a full result means "possibly truncated".
- An `OPTIONAL MATCH` after an aggregating `WITH` returned no rows.
- Aggregating `SSpaths` output together with a null property crashed the server. We aggregate per node first.
- An unanchored pattern comprehension returned an empty list.

## Try it

- `make judge-check`: keyless, prints PASS.
- The incident room at `/incidents`, the replay at `/replay/s1-hero`, the company brain at `/brain`, preflight at `/preflight`.
- Query the same read-only tools over MCP: `docs/MCP.md`.
