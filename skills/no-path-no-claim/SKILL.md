---
name: no-path-no-claim
description: Blame a change for an incident only when a FalkorDB graph proves it - a causal path from the change to the symptom (algo.SPpaths) and enough failure capacity to carry the observed impact (algo.maxFlow). Use with any agent that has a read-only FalkorDB connection (for example the official FalkorDB MCP server's query_graph_readonly) and a graph with Deploy -[:CHANGED]-> component, PROPAGATES_TO {cap, w} failure edges and MetricWindow telemetry.
---

# No path, no claim

Faultline's evidence gate, reduced to the two checks any agent can run with nothing but read-only Cypher. It does
not need Faultline's code: the four queries in `queries/` are the whole method.

## The rule
A change may be named as the cause of a symptom only when BOTH hold:
1. **G2, a path exists.** `queries/2_path.cypher` returns at least one chain from the change to the symptom over
   `CHANGED|GATES|PROPAGATES_TO`, at most 8 hops. No row: the change cannot be claimed, however plausible it looks.
2. **G5, the path can carry the impact.** `queries/4_flow.cypher` (max flow from the changed component to the
   symptom over `PROPAGATES_TO.cap`) is at least 0.8 × the observed share from `queries/3_observed.cypher`.
   A change made on the symptom itself passes this check trivially.

If exactly one change passes both, name it. If none passes, say "no change in the window explains this" and escalate.
If several pass, say so and do not pick one. Never fall back to "the most recent deploy".

## Steps
1. `queries/1_suspects.cypher` with the alert's onset (epoch ms) and a 30-minute window: the suspects.
2. For each suspect: `queries/2_path.cypher`. Drop the ones with no row (report them as "no path").
3. `queries/3_observed.cypher` for the symptom (baseline = 30 to 5 minutes before onset).
4. For each remaining suspect: `queries/4_flow.cypher`; drop those below 0.8 × observed (report "cannot carry it").
5. Report the survivors with their chain and their max flow; cite the query and the parameters for each claim.

## Over the official FalkorDB MCP server
Run each query with `query_graph_readonly` (graph = the tenant graph) and the parameters above. The server's
read-only user is enough: nothing here writes.

## What this skill does not do
Faultline's gate has six more checks (grounding, timing, origin, multiplicity, completeness, decisions) and runs on
fresh evidence per run; this skill is the core claim rule only. `scripts/skill_check.py` measures how often its
verdicts agree with the full gate on the scenario clean rooms. Known gap: a symptom with no error-rate windows (a KPI
fed by a data pipeline) has no observed share for step 3, so the skill names nobody there; Faultline's gate measures
the anomalous row share in the warehouse instead. The skill then abstains; it never blames the wrong change.
