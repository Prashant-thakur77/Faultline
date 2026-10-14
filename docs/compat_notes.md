<!-- Appended verbatim to docs/FALKORDB_COMPAT.md by scripts/render_compat.py: checks verified by live tests outside the smoke suite. -->

## Official MCP server under the read-only ACL user (verified 2026-10-13)
`@falkordb/mcpserver@1.3.0` with `FALKORDB_STRICT_READONLY=true` under our `ro_<tenant>` line (no `GRAPH.LIST`):
- **Startup needs `+info`.** Without it, the server hangs silently and never answers `initialize` (docs/upstream/14). `+info` is now in `deploy/users.acl.template`.
- **With `+info`:**
  - `query_graph_readonly` on its own tenant works;
  - `query_graph` with a write is refused ("only read-only queries");
  - another tenant gets NOPERM;
  - `list_graphs` gets NOPERM, so no graph names leak.

Test: `tests/mcpserver/test_official_mcpserver_acl.py`.

## UDFs and FalkorDB FLEX (verified 2026-10-13)
- **`GRAPH.UDF LOAD/LIST/DELETE` works on 6.0.2,** and a UDF is callable inside `GRAPH.RO_QUERY`.
- **Library:** FLEX 1.0.1 (`deploy/udf/flex-1.0.1.js`, sha256-pinned) is loaded by `backend/faultline/graph/udf.py` (`make up` via `scripts/configure_falkordb.py`, seed, and API startup); `/api/status` reports it from `GRAPH.UDF LIST` and judge-check checks the loaded sha.
- **Used in templates:**
  - `flex.text.jaroWinkler` in Q-FIND-FUZZY: the misspelling "pyment" resolves to payment above the `brain.fuzzy_min` floor (asserted in the live test), behind a length-ratio and first-letter guard;
  - `flex.sim.jaccard` in Q-COUPLE-1, for coupling strength.
- Test: `tests/live/test_flex_udf.py`.
