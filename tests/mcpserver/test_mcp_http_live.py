"""Live: MCP over Streamable HTTP with bearer keys → tenant binding, 401 without a key, 429 over the rate limit,
and the guarded text2cypher tool reachable remotely (writes rejected by the guard)."""

import socket
import threading
import time

import anyio
import httpx
import pytest
import uvicorn

from faultline.mcp_server.http import build_http_app

pytestmark = pytest.mark.live

KEY = "test-key-acme-0123456789abcdef"


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def server():
    port = _port()
    url = f"http://127.0.0.1:{port}"
    app, _ = build_http_app({KEY: "acme"}, public_url=url, per_min=12)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield url
    srv.should_exit = True
    th.join(timeout=5)


async def _call(url: str, tool: str, args: dict, key: str = KEY):
    from mcp.client import Client
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async with create_mcp_http_client(headers={"Authorization": f"Bearer {key}"}) as http:
        async with Client(streamable_http_client(f"{url}/mcp", http_client=http)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            res = await c.call_tool(tool, args)
            return names, res.structured_content


def test_no_key_is_401(server):
    r = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401
    r = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream", "Authorization": "Bearer wrong-key-000000000000000"})
    assert r.status_code == 401


def test_causal_paths_over_http_bound_to_tenant(server):
    names, out = anyio.run(_call, server, "causal_paths", {"from_id": "payment", "to_id": "checkout"})
    assert {"causal_paths", "impact_bound", "run_cypher_readonly", "similar_incidents"} <= names
    assert not names & {"rank_causes", "whatif", "who_fixes", "escalation_tree"}  # scratch-graph writers: never hosted
    assert out.get("rows"), out
    assert "tenant_acme" in out["served_by"] and "GRAPH.RO_QUERY" in out["served_by"]


def test_text2cypher_guard_over_http(server):
    _, out = anyio.run(_call, server, "run_cypher_readonly",
                       {"query": "MATCH (n:Service) DETACH DELETE n", "failed_template": "Q-CTX-1",
                        "reason": "testing that writes are refused"})
    assert "guard rejected" in out["error"]
    _, out = anyio.run(_call, server, "run_cypher_readonly",
                       {"query": "MATCH (s:Service {id:'payment'})-[:PROPAGATES_TO*1..2]->(t) RETURN t.id AS id ORDER BY id",
                        "failed_template": "Q-BLAST-1", "reason": "two-hop reach of payment, no template for this shape"})
    assert out["template"] == "T2C" and out["via"] == "text2cypher" and out["cypher"].endswith("LIMIT 100")
    assert {r["id"] for r in out["rows"]} >= {"checkout"}


def test_rate_limit_is_429(server):
    codes = []
    for _ in range(14):
        r = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                       headers={"Accept": "application/json, text/event-stream", "Authorization": "Bearer rl-key-0000000000000000000000"})
        codes.append(r.status_code)
    assert 429 in codes


def test_public_host_behind_the_proxy_is_accepted_and_foreign_hosts_are_not():
    """Review round 4 (B1): Caddy forwards Host: <domain>. The SDK default allowed only localhost → 421 for every
    real request. The public host is allowed now; DNS-rebinding protection still refuses any other Host."""
    from starlette.testclient import TestClient

    app, _ = build_http_app({KEY: "acme"}, public_url="https://faultline.example", per_min=50)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
    hdrs = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {KEY}"}
    with TestClient(app, base_url="https://faultline.example") as c:
        ok = c.post("/mcp", json=init, headers=hdrs)
        assert ok.status_code == 200, ok.text
        bad = c.post("/mcp", json=init, headers={**hdrs, "Host": "evil.example"})
        assert bad.status_code == 421
