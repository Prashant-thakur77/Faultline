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

## Engine depth on 6.0.2 (verified 2026-10-17; smoke rows 25–30, live tests named below)
- **Constraints (`GRAPH.CONSTRAINT`).** `GRAPH.CONSTRAINT CREATE <graph> MANDATORY|UNIQUE NODE|RELATIONSHIP <label> PROPERTIES <n> <p…>`; status from `CALL db.constraints() YIELD type, label, properties, entitytype, status` (`YIELD *` is a syntax error), PENDING then OPERATIONAL. UNIQUE needs the exact-match range index first.
  - A MANDATORY property set by `MERGE … ON CREATE SET` or a later `SET` in the same query passes (checked at commit). A batch with one bad row rolls back whole. `GRAPH.COPY` carries every constraint and the copy enforces it.
  - Messages: `mandatory constraint violation: node with label Evidence missing property digest`, `… edge with relationship-type PROPAGATES_TO missing property cap`, `unique constraint violation on node of type Node`. A second `Constraint already exists` CREATE is an error (tolerated by `writes.ensure_constraints`).
  - Faultline's set: `graph/constraints.py`; tests: `tests/live/test_constraints.py`.
- **`QUERY_MEM_CAPACITY`** (bytes per query): settable at runtime (`GRAPH.CONFIG SET`) and as a load-time `FALKORDB_ARGS` value (checked in a throwaway container by `scripts/egress_check.py`). Over it: `Query's mem consumption exceeded capacity`; the RO wrapper raises `GraphMemoryCapExceeded`. Test: `tests/live/test_mem_cap.py`.
- **Vector index options.** `CREATE VECTOR INDEX FOR (n:L) ON (n.p) OPTIONS {dimension, similarityFunction, M, efConstruction, efRuntime}`; read back in `db.indexes()` `options`; `DROP VECTOR INDEX FOR (n:L) ON (n.p)`. **efRuntime is an index option only**: the map form `db.idx.vector.queryNodes({…, efRuntime})` is refused (`Received 1 arguments … expected at least 4`).
  - **An index built over existing nodes is asynchronous**: `db.indexes()` `status` reads `[Indexing] i/n: UNDER CONSTRUCTION` until OPERATIONAL, and a vector query meanwhile reads a partial index (silently missing neighbours). `writes.apply_schema` waits for OPERATIONAL after a rebuild.
  - Measured recall: `evals/vector_recall.py` (keys `vector.*` in `evals/results/latest.json`).
- **Aggregates.** `avg`, `stDevP`, `percentileCont(x, 0.95)` skip the nulls of `CASE WHEN … THEN x END`; over no rows `avg` is null and `stDevP` is 0. They can differ from Python's `fmean` / `pstdev` in the last bit, so the 4-place rounding of the gate band stays in Python. Test: `tests/live/test_band_in_engine.py`.
- **Temporal (wall-clock rules).** Works: `localdatetime('1970-01-01T00:00:00') + duration({seconds: toInteger($ms / 1000) + offset_s})`, then `.dayOfWeek`, `.weekDay`, `.hour`, `.minute`.
  - **`.dayOfWeek` returns 0 for Sunday** (openCypher: 7); `.weekDay` returns 7. Q-PRE-FREEZE reads 0 as 7, so it is right under either convention.
  - Silent wrong results (never use): `duration({milliseconds: 90000})` is `PT0S`; `localdatetime({epochMillis: …})` is `1970-01-01T00:00:00`. No time zones: policies carry a fixed UTC offset (no DST). Known upstream (FalkorDB#3295, #2936): `docs/upstream/23-temporal-silent-errors.md`.
- **`dbms.functions()`**: `YIELD name, udf, aggregation` (`signature` / `description` do not exist). Built-in names are listed lower-cased and match case-insensitively; FLEX UDFs carry `udf = true`. Test: `tests/mcpserver/test_guard_functions.py`.
- **`telemetry{<graph>}` stream**: one entry per query with `Received at`, `Query`, `Query parameters`, `Total duration`, `Wait duration`, `Execution duration`, `Report duration` (ms), `Utilized cache`, `Write`, `Timeout`; written just after the reply; deleted with the graph. Read with `XREVRANGE telemetry{<graph>} + - COUNT n` (engine user). Test: `tests/live/test_engine_insight.py`.
- **`WAITAOF numlocal numreplicas timeout`** on the connection that wrote returns `[1, 0]` once the write is fsynced (appendfsync everysec: about one second); with `numreplicas 1` and no replica it times out and returns `[1, 0]` after the timeout. Test: `tests/live/test_durable_writeback.py`.
- **No internet egress in production.** On an `internal: true` Docker network a remote `LOAD CSV` fails (`DNS resolution failed` by name, `Network is unreachable` by IP literal), so the engine cannot reach out. `scripts/egress_check.py`, `tests/live/test_egress.py`; finding 22 in `docs/upstream/` was reported privately.
