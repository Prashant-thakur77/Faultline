# Faultline explained in one page

The Graph Hacks rules ask participants to be able to explain the graph model, the queries, the architecture and the decisions. This page holds the answers. Each section is one question a judge might ask.

## "What is it, in one sentence?"
An on-call agent that is not allowed to blame a change until FalkorDB returns a causal path, and that rejects look-alike causes with a max-flow bound. It then contains the incident with a min-cut, routes it to the right person, takes one human-approved action, verifies it through a second channel and writes the decision back so the next incident starts warm.

## "Why does it need a graph? Couldn't you use a table or vector search?"
Two deploys land in the same minute and both mention payment and checkout. Vector similarity scores them the same, and so does a table of recent changes. The graph answers two structural questions instead:
1. Is there a path from the change to the broken thing? (`algo.SPpaths`; no path means no claim.)
2. Could that path carry the observed failure? (`algo.maxFlow`: the email deploy can carry at most <!-- claim:s1.D-email-88.max_flow -->0.02<!-- /claim --> of checkout's errors; explaining what we see needs <!-- claim:s1.D-email-88.needed -->0.2433<!-- /claim -->, the observed share <!-- claim:s1.D-email-88.observed -->0.3041<!-- /claim --> with slack for noise.)

Neither question can be expressed as a similarity score. Switch the max-flow check off (arm A3-noG5) and top-1 drops from <!-- claim:arm.A3.top1 -->1.0<!-- /claim --> to <!-- claim:arm.A3-noG5.top1 -->0.8<!-- /claim -->: on the data incident the look-alike survives, so the agent cannot decide. (On S1 the sweep's origin test still rejects the email deploy, because the email service is measured healthy.) Switch FalkorDB off (A4) and the run cannot start: it confirms <!-- claim:arm.A4.confirmed_causes -->0<!-- /claim --> causes.

## "What's in the graph?"
One graph per tenant. It holds:
- services and their calls (OpenTelemetry Demo);
- the data pipeline lineage (tables, columns, transforms, KPI);
- deploys, PRs, commits and files;
- people, teams and on-call;
- ADRs, runbooks and postmortems;
- incidents, evidence, hypotheses, gate runs, approvals, intents and actions.

A derived `PROPAGATES_TO` layer gives the direction failure flows, with a capacity `cap`. See `docs/design/graph_model_sketch.md`.

## "What does `cap` mean, and why is the max-flow test valid?"
- **Service edges:** `cap` = criticality. 1.0 for a synchronous call whose errors propagate; 0.02 for a best-effort call such as the order-confirmation email. <!-- noclaim: configured capacities -->
- **Lineage edges:** `cap` = the share of rows derived from that input. The FX feed only touches non-USD rows: max flow <!-- claim:s2.D-fx-pause-7.max_flow -->0.0692<!-- /claim --> of the KPI.
- **Why it's valid:** max-flow over these capacities, multiplied by the number of distinct failure paths k from the change to the symptom, is an **upper bound** on how much of the symptom a single cause can explain. The multiplier is there because a request can meet the same fault once per path. Every rejection in the scenarios has k = 1, where it is plain max-flow. A property test on random graphs checks the bound against the simulator (`tests/graph/test_g5_bound_property.py`); it is what found the reconvergent case. So if even the bound is below the observed impact, the suspect is eliminated.
- **Two causes at once:** a suspect is only eliminated if the remaining suspects *together* can explain the impact (one multi-source max-flow call). Otherwise the agent says "not confident".
- **Honest limits:** single-cause assumption by default (joint sufficiency is reported as "not confident"); the capacities are modelled from criticality and row share, not learned from traffic.

## "How does the agent decide? Is the LLM in charge?"
No. The model proposes; deterministic code backed by read-only queries decides. The Evidence Gate has eight checks:
- **G1 grounded:** every id was seen in a tool result this run.
- **G2 path:** the change reaches the symptom.
- **G3 time order:** the change came before the onset, inside the window.
- **G4 quantitative:** a metric on the path is outside its baseline band.
- **G5 sufficiency:** the max-flow bound covers the observed impact.
- **G6 competitors:** every rival cause is eliminated or unresolved.
- **G7 agreement:** at least two independent evidence sources on the causal chain (e.g. the graph and telemetry) agree; otherwise "not confident".
- **G7 correlation:** the change specialist and the code (or, for data incidents, the data) specialist name the same deploy, and that deploy CHANGED a node of the chain. If they point at different changes, the verdict is "not confident". If no code or data channel could inspect any change, the check says "not evaluable".
- **G8 contradiction:** active decisions (ADRs) the cause violates are attached.

At the gate a deterministic competitor sweep checks every change in the window, so distractors are rejected on every run, not only when the model thinks to test them. The sweep eliminates a change by no path (G2), by insufficient flow (G5), or by the origin tests: its own component was measured healthy while another suspect's is anomalous, or it is anomalous only by what an anomalous component upstream carries to it (G4 upstream: the look-alike that is broken because something above it broke).

## "Which FalkorDB features, and where?"
- **<!-- claim:repo.algorithms -->10<!-- /claim --> `algo.*` procedures, each its own MCP tool that changes a decision:**
  - BFS (blast radius, scope)
  - SPpaths (G2)
  - SSpaths (the "no incident" negative proof)
  - pageRank (investigation order)
  - betweenness (chokepoints, preflight risk)
  - HarmonicCentrality (who fixes it)
  - WCC (what-if: still connected?)
  - labelPropagation (incident families)
  - maxFlow (G5 and the min-cut)
  - MSF (escalation tree)
- **Reads:** every read goes through `GRAPH.RO_QUERY` with a timeout and a LIMIT, under an ACL read-only user.
- **Vectors and full-text:** `vecf32` vectors as recall seeds, plus the full-text DDL form.
- **Per-tenant graphs:** with `GRAPH.COPY` for golden snapshots, re-arm, what-if branches and eval clean rooms.
- **Write-back:** a single-query, atomic write-back, re-read through a separate connection (`verified n/m`).
- **Our MCP server:** typed, tenant-bound tools.
- **The official FalkorDB MCP server:** strict read-only, for judges.

## "What happens when something fails?"
It fails loudly. If FalkorDB is down, the UI shows a banner and no answer is invented.
- **Verification has three outcomes:** APPLIED / NOT_APPLIED / UNKNOWN. UNKNOWN goes to a human and never writes success.
- **Approval has two steps:** choosing an option is not approving it. The exact action is bound by a plan hash.

## "What if no change explains it?"
The agent abstains rather than blaming the nearest deploy (S12). It measures the symptom's upstream components, and a query picks the upstream-most anomalous node that no change touched (Q-INFER-1). That node is reported as an *inferred, unconfirmed* origin (`NOT_CONFIDENT`). Only tracking (an issue) is offered until a human confirms it.

## "What does memory actually do?"
- **Recall** uses the incident's own vector in FalkorDB's index, then requires a shared `Symptom` node. Families come from `algo.labelPropagation`. Repeated APPLIED fixes become a derived runbook with provenance. Failed attempts are remembered as `ATTEMPTED`.
- **Memory only reorders.** On two repeat incidents (S1b, S3b) the gate's verdicts are identical cold and warm (<!-- claim:memory.gate_verdicts_identical -->True<!-- /claim -->); the warm run's top precedent is the incident just resolved.
- **Forget** works with a receipt: a dry run lists exactly what one document alone produced; executing needs that exact set's token; the receipt goes to the audit graph; the vectors provably stop coming back.

## "And the company brain / preflight?"
- **Brain:** id and full-text seeds → templates → guarded text2cypher (last resort). Every cited `[id]` must have been seen by that question's own tool calls, and a read-only query decides.
- **Preflight:** a PR is ingested as `(:PR)-[:TOUCHES]->(:File)` plus ChangeFacts from config diffs. BFS impact, betweenness, past incidents, contradicted ADRs, bus factor and gaps give allow / require_review / block. S6 → <!-- claim:s6.verdict -->block<!-- /claim -->.

## "Does the graph know about time?"
Yes. Ownership and on-call carry validity windows (`OWNED_AT {from, to}`, `ON_CALL {from, to}`), and decisions carry `decided_at` and `SUPERSEDES`. One query answers "what did we believe about X as of a date or an incident": the owner, who was on call, the decisions in force and the runbooks in effect. The incident report says who owned the changed component when the change shipped. After a handover, it lists the people from the old team who worked on it.

## "How does it know what it doesn't know?"
`knowledge_health` finds three kinds of decay:
- runbooks nobody has reviewed for a quarter, or that predate the current owner;
- components that changed hands with no runbook since;
- decisions whose owners changed.

`hidden_coupling` finds component pairs that keep failing together in incident history although the graph has no failure path between them. That is the graph pointing at its own missing edges. It is never used as evidence: the gate still says "no path, no claim".

## "Did you test that the safety checks matter?"
`make mutants` breaks each safety invariant in a scratch copy of the code, then runs the tests that should notice: the gate checks, suspect discovery, storm grouping, the plan hash, UNKNOWN never success, the verify allowance, reorder-only ordering, tool whitelists, specialist claims, RO-only reads, the A4 ablation, the lint, the guard, the citation guard and tenancy. On the eval run <!-- claim:mutation.killed -->43<!-- /claim -->/<!-- claim:mutation.mutants -->43<!-- /claim --> were caught. Each mutant runs under a memory cap, so a mutant that makes code run away (it happened once) dies alone.

## "Would the pre-deploy gate have caught past incidents?"
We replayed every historical PR as of its merge time. On globex it ranks the causing PRs well (AUROC <!-- claim:backtest.globex.full.all.auroc -->0.8075<!-- /claim -->), mostly through the memory term. On acme it is no better than chance once the topology is read as of each merge (AUROC <!-- claim:backtest.acme.full.all.auroc -->0.5179<!-- /claim -->), and at its threshold no better than random picking and flags too many PRs. We report that rather than re-tune the pre-registered thresholds.

## "Is it safe to put on a public URL?"
Yes, as a demo. See `SECURITY.md`:
- choose/approve need the run's own token;
- forget and preflight from visitors run on clean-room copies;
- there is no anonymous LLM spend;
- per-visitor and global rate limits;
- FalkorDB is never exposed.

## "Does it scale past a toy?"
The second tenant, globex, has <!-- claim:repo.globex.services -->200<!-- /claim --> services, <!-- claim:repo.globex.persons -->180<!-- /claim --> people and <!-- claim:repo.globex.incidents -->150<!-- /claim --> incidents in <!-- claim:repo.globex.families -->8<!-- /claim --> families, in its own graph. Isolation, recurring families and owner-gone routing are checked there (S7, S8, S11). Large views are focus-scoped, and they say when they are truncated instead of pretending to be whole.
