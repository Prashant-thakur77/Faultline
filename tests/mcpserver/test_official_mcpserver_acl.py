"""Live: the official @falkordb/mcpserver (the judges' raw read-only path) under our exact ro_<tenant> ACL line.
It must start without GRAPH.LIST, read its own tenant, refuse writes, be denied other tenants and the graph list."""

import asyncio
import os
import re
import secrets
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def _acl_line(user: str, pw: str) -> list[str]:
    line = next(ln for ln in (ROOT / "deploy" / "users.acl.template").read_text().splitlines() if ln.startswith("user ro_acme "))
    line = line.replace("ro_acme", user, 1).replace("${FALKORDB_RO_PASSWORD}", pw)
    return line.split()[1:]


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx not installed")
def test_official_mcpserver_under_the_ro_acl_line(db):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    user, pw = f"ro_probe_{secrets.token_hex(3)}", secrets.token_hex(16)
    acl = _acl_line(user, pw)
    assert "+graph.list" not in [a.lower() for a in acl]          # never granted: it leaks every graph name
    db.connection.execute_command("ACL", "SETUSER", *acl)
    # --prefer-offline: the pinned package comes from the local npm cache when it is there (a registry round trip
    # under load once timed this test out inside judge-check: 2026-10-13)
    params = StdioServerParameters(command="npx", args=["-y", "--prefer-offline", "@falkordb/mcpserver@1.3.0"], env={
        **os.environ, "FALKORDB_HOST": os.getenv("FALKORDB_HOST", "localhost"), "FALKORDB_PORT": os.getenv("FALKORDB_PORT", "6379"),
        "FALKORDB_USERNAME": user, "FALKORDB_PASSWORD": pw, "FALKORDB_DEFAULT_READONLY": "true", "FALKORDB_STRICT_READONLY": "true"})

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await asyncio.wait_for(s.initialize(), 90)
                out = {}
                for key, name, args in [
                    ("own", "query_graph_readonly", {"graphName": "tenant_acme", "query": "MATCH (s:Service) RETURN count(s) AS n"}),
                    ("write", "query_graph", {"graphName": "tenant_acme", "query": "CREATE (:Probe {x: 1})"}),
                    ("other", "query_graph_readonly", {"graphName": "tenant_globex", "query": "MATCH (n) RETURN count(n)"}),
                    ("list", "list_graphs", {})]:
                    res = await asyncio.wait_for(s.call_tool(name, args), 30)
                    err = getattr(res, "is_error", getattr(res, "isError", False))
                    out[key] = (bool(err), " ".join(getattr(c, "text", "") for c in res.content))
                return out

    try:
        try:
            out = asyncio.run(go())
        except* TimeoutError:  # one retry for the external npx process starting slowly; a second timeout fails
            out = asyncio.run(go())
    finally:
        db.connection.execute_command("ACL", "DELUSER", user)
    assert not out["own"][0] and re.search(r'"n":\s*\d+', out["own"][1])                  # reads its own tenant
    assert out["write"][0] and "read-only" in out["write"][1]                              # strict read-only
    assert out["other"][0] and "NOPERM" in out["other"][1]                                 # tenant isolation
    assert out["list"][0] and "NOPERM" in out["list"][1]                                   # no graph-name leak
    assert db.select_graph("tenant_acme").ro_query("MATCH (p:Probe) RETURN count(p)").result_set[0][0] == 0
