# @falkordb/mcpserver 1.3.0 hangs silently at startup when the user may not run INFO

**Status:** not filed (repro and draft here; for FalkorDB-MCPServer).

**Setup.** A restricted Redis ACL user for read-only graph access:
`resetchannels -@all +graph.ro_query +graph.explain +ping +hello +client|setname +client|setinfo ~tenant_acme`, with
`FALKORDB_USERNAME`/`FALKORDB_PASSWORD` set, `FALKORDB_STRICT_READONLY=true`.

**Actual.** `npx -y @falkordb/mcpserver@1.3.0` prints nothing and never answers `initialize` (stdio). No log line and
no error reaches the client, which times out (Claude Code shows `CONNECT_TIMEOUT`). The ACL log records no denial for the user.

**Bisect.** Adding `+info` alone fixes it: the server then starts, `query_graph_readonly` works on the permitted
graph, writes are refused, other graphs return NOPERM and `list_graphs` returns NOPERM (GRAPH.LIST is not granted).
`+graph.list`, `+module|list` or `+@connection` do not help.

**Expected.** Either no INFO dependency for restricted users, or a clear startup error ("INFO denied: grant +info")
instead of a silent hang.

**Workaround.** Grant `+info` (server statistics and key counts; no graph names). See `deploy/users.acl.template`
and `tests/mcpserver/test_official_mcpserver_acl.py`.
