# Upstream FalkorDB issue drafts (from `make smoke-both`; minimal repros, no secrets)

Each draft is reproducible with the pinned digests in docs/FALKORDB_COMPAT.md. Each was re-run on the pinned engine and checked against FalkorDB's issue tracker before filing: new bugs become new issues, and where the bug is already known the new evidence (engine version, smaller repro) goes into the existing thread. Status below.

| # | Title | Engine | Status |
|---|---|---|---|
| 1 | `algo.betweenness` ranks the wrong node on a 5-node path (v4.22.0) | v4.22.0 | ready to file (new): scores depend on the seed even with samplingSize ≥ node count |
| 2 | Conditional MERGE claim yields two owners under 16-way contention (v4.22.0; 6.0.2 OK) | v4.22.0 | ready to file (new): concurrent MERGE on a not-yet-existing label creates duplicates |
| 3 | Docs: `algo.maxFlow` accepts only the map form with node arrays (positional/id forms in the May news post do not exist) | both | no action: the docs page is correct (the wrong forms were in a news post) |
| 4 | Docs: `algo.SSpaths` `pathCount` is a global top-k over all targets; 0 returns only minimum-weight ties | both | ready to file (new, docs repo) |
| 5 | `EXISTS { MATCH … }` subqueries unsupported (6.0.2 and v4.22.0) | both | known upstream: FalkorDB#2161 |
| 6 | 6.0.2: `db.idx.fulltext.createNodeIndex` procedure form rejected (DDL works) | 6.0.2 | known upstream: FalkorDB#2540 (confirm on 6.0.2) |
| 7 | OPTIONAL MATCH after an aggregating WITH returns no rows (multi-hop pattern) | 6.0.2 | related to FalkorDB#3037 (comment prepared) |
| 8 | **Server panic** on algo.SSpaths + aggregation grouped with a null property (read-only query crashes the process) | 6.0.2 | same panic as FalkorDB#3150 (fix PR #3229); **posted** [a smaller repro and two more triggers](https://github.com/FalkorDB/FalkorDB/issues/3150#issuecomment-6201125566) |
| 9 | Pattern comprehension with a relationship-property filter returns [] when another comprehension follows | 6.0.2 | related to FalkorDB#3004 (comment prepared) |
| 10 | Unanchored pattern comprehension silently returns [] (docs/error request) | 6.0.2 | not reproduced on a fresh 6.0.2 graph: withdrawn |
| 11 | Pattern comprehension mixing a relationship and a node predicate returns [] after an aggregating WITH | 6.0.2 | related to FalkorDB#3004 (comment prepared) |
| 12 | Pattern comprehension over an anonymous relationship collapses parallel edges (one element per end node) | 6.0.2 | known upstream: FalkorDB#2501 (dup of #1848); comment prepared |
| 13 | A filtered pattern comprehension after an aggregating WITH returns [] unless one MATCH precedes the aggregation and the filter is on the relationship only | 6.0.2 | related to FalkorDB#3004 (comment prepared) |
| 14 | @falkordb/mcpserver 1.3.0 hangs silently at startup when the ACL user may not run INFO | mcpserver 1.3.0 | ready to file (new, FalkorDB-MCPServer) |
| 15 | `algo.WCC` fails (`LAGr_ConnectedComponents failed: -1000`) on a graph with exactly one node | 6.0.2 | **filed** as [FalkorDB#3349](https://github.com/FalkorDB/FalkorDB/issues/3349): fails whenever the label set holds one node; pageRank too |
| 16 | **Silent wrong result**: WITH/UNWIND followed by two MATCH clauses (the first disconnected) drops the WITH's rows (scale benchmark) | 6.0.2 | known upstream: FalkorDB#3343 / #2972 (form 1); related to #3037 (form 2) |
| 17 | **Silent wrong result**: a CALL {} subquery after OPTIONAL MATCH filters on a node before binding it (who_fixes in Cypher) | 6.0.2 | related to FalkorDB#3037 (comment prepared) |
| 18 | **Silent wrong result** (no index) / spurious error (index): a node's inline map reading a variable bound by the previous MATCH (learned edges) | 6.0.2 | known upstream: FalkorDB#2923 |
| 19 | **Silent wrong result**: a MATCH after a `CALL {}` subquery ignores a node variable bound before the subquery and matches every node (deep bench, Q-GATE-UPSTREAM) | 6.0.2 | related to FalkorDB#2972 (variable-length only; comment prepared) |
| 20 | **Silent wrong result**: a MATCH whose WHERE holds a pattern comprehension, followed by another MATCH, drops the row (on-call escalation write) | 6.0.2 | not yet searched upstream; repro in 20-match-where-comprehension-then-match.md |
| 21 | **Silent wrong result**: a single-node MATCH grouped by two properties returns the first aggregate in every aggregate column; a slice next to a count DISTINCT ordered by a grouping key errors (contract suggestions, M21) | 6.0.2 | not yet searched upstream; repro in 21-two-property-keys-collapse-aggregates.md |
| 22 | Remote `LOAD CSV` cannot be disabled and runs under `GRAPH.RO_QUERY` with a URL built from graph data (an outbound channel for read-only users) | 6.0.2 | draft (M20): not yet searched upstream; feature request; repro and network check in 22-load-csv-egress.md |
| 23 | **Silent wrong results**: `localdatetime({epochMillis})` is 1970, `duration({milliseconds})` is PT0S, unknown temporal keys are ignored, `dayOfWeek` is 0 on Sunday | 6.0.2 | draft (M20): possibly the #3295 family, search first; 23-temporal-silent-errors.md |
| 24 | A relationship range index slows anchored and labelled traversals 13× to 240× (one scan times out) | 6.0.2 | draft (M20): not yet searched upstream; 24-edge-index-planner.md |
| 25 | Every insert under a UNIQUE constraint costs time proportional to the label's size (1,000 MERGEs: 0.005 s without, 5.2 s with, at 19k nodes) | 6.0.2 | draft (M20): not yet searched upstream; 25-unique-constraint-insert-cost.md |

## Filed upstream (2026-10-17)

- [FalkorDB/GraphRAG-SDK#345](https://github.com/FalkorDB/GraphRAG-SDK/pull/345): fix for GraphRAG-SDK#344. Fulltext indexes are created with the `CREATE FULLTEXT INDEX` DDL, vector indexes are dropped with `DROP VECTOR INDEX`, and rejected statements no longer feed the circuit breaker. On 6.0.2 the SDK's full suite goes from 124 failures to the 2 environment-only ones that also fail on `main`; tested on 4.18.0, 4.22.0 and 6.0.2.
- [FalkorDB#3376](https://github.com/FalkorDB/FalkorDB/issues/3376): a relationship range index makes traversals from bound nodes much slower on 6.0.2 (5 ms → 5.4 s, draft 24).
- [FalkorDB#3377](https://github.com/FalkorDB/FalkorDB/issues/3377): the Docker image's default `IMPORT_FOLDER` does not exist, so `LOAD CSV FROM 'file://…'` fails out of the box.
- [New evidence on FalkorDB#2502](https://github.com/FalkorDB/FalkorDB/issues/2502#issuecomment-6237945777): the pattern-comprehension form of draft 20 silently drops the row.
- Remote `LOAD CSV` under `GRAPH.RO_QUERY` (draft 22) was reported privately through FalkorDB's vulnerability reporting, not as a public issue; Faultline's own deployment closes it with an internal-only network.
- Earlier: [FalkorDB#3349](https://github.com/FalkorDB/FalkorDB/issues/3349) and [new evidence on #3150](https://github.com/FalkorDB/FalkorDB/issues/3150#issuecomment-6201125566).
- Drafts 21, 23 and 25 turned out to be known upstream (FalkorDB#3375 with fix PR #3374; #3295 and #2936; #3330, fixed by #3334 after 6.0.2), so they were not refiled.
