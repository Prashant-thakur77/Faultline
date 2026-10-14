# Upstream FalkorDB issue drafts (from `make smoke-both`; minimal repros, no secrets)

Each draft is reproducible with the pinned digests in docs/FALKORDB_COMPAT.md. They are posted to github.com/FalkorDB/FalkorDB after one more confirmation run. Links are recorded here once posted.

| # | Title | Engine | Status |
|---|---|---|---|
| 1 | `algo.betweenness` ranks the wrong node on a 5-node path (v4.22.0) | v4.22.0 | draft |
| 2 | Conditional MERGE claim yields two owners under 16-way contention (v4.22.0; 6.0.2 OK) | v4.22.0 | draft |
| 3 | Docs: `algo.maxFlow` accepts only the map form with node arrays (positional/id forms in the May news post do not exist) | both | draft |
| 4 | Docs: `algo.SSpaths` `pathCount` is a global top-k over all targets; 0 returns only minimum-weight ties | both | draft |
| 5 | `EXISTS { MATCH … }` subqueries unsupported (6.0.2 and v4.22.0) | both | draft |
| 6 | 6.0.2: `db.idx.fulltext.createNodeIndex` procedure form rejected (DDL works) | 6.0.2 | draft |
| 7 | OPTIONAL MATCH after an aggregating WITH returns no rows (multi-hop pattern) | 6.0.2 | draft |
| 8 | **Server panic** on algo.SSpaths + aggregation grouped with a null property (read-only query crashes the process) | 6.0.2 | draft (high priority) |
| 9 | Pattern comprehension with a relationship-property filter returns [] when another comprehension follows | 6.0.2 | draft |
| 10 | Unanchored pattern comprehension silently returns [] (docs/error request) | 6.0.2 | draft |
| 11 | Pattern comprehension mixing a relationship and a node predicate returns [] after an aggregating WITH | 6.0.2 | draft |
| 12 | Pattern comprehension over an anonymous relationship collapses parallel edges (one element per end node) | 6.0.2 | draft |
| 13 | A filtered pattern comprehension after an aggregating WITH returns [] unless one MATCH precedes the aggregation and the filter is on the relationship only | 6.0.2 | draft |
| 14 | @falkordb/mcpserver 1.3.0 hangs silently at startup when the ACL user may not run INFO | mcpserver 1.3.0 | draft |
| 15 | `algo.WCC` fails (`LAGr_ConnectedComponents failed: -1000`) on a graph with exactly one node | 6.0.2 | draft |
| 16 | **Silent wrong result**: WITH/UNWIND followed by two MATCH clauses (the first disconnected) drops the WITH's rows (scale benchmark) | 6.0.2 | draft |
| 17 | **Silent wrong result**: a CALL {} subquery after OPTIONAL MATCH filters on a node before binding it (who_fixes in Cypher) | 6.0.2 | draft |
| 18 | **Silent wrong result** (no index) / spurious error (index): a node's inline map reading a variable bound by the previous MATCH (learned edges) | 6.0.2 | draft |
| 19 | **Silent wrong result**: a MATCH after a `CALL {}` subquery ignores a node variable bound before the subquery and matches every node (deep bench, Q-GATE-UPSTREAM) | 6.0.2 | draft |
