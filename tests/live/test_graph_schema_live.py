"""Live: the graph_schema tool, the faultline:// resources and the prompts through real MCP sessions (in-memory and
Streamable HTTP with bearer keys), tenant binding, engine-exact counts, and the schema drift check on the live graphs
plus a throwaway scratch graph carrying an undeclared label and type. Read-only on the tenant graphs."""

import json
import socket
import threading
import time
import uuid

import anyio
import pytest
from mcp.client import Client

from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO
from faultline.graph.schema_introspect import drift, introspect
from faultline.graph.tenant import scratch_graph
from faultline.mcp_server import context
from faultline.mcp_server.server import build_server

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def seeded(db):
    for t in ("acme", "globex"):
        if not gcopy.exists(db, f"tenant_{t}"):
            pytest.skip(f"{t} not seeded")


def _session(fn, tenant: str | None = None):
    async def go():
        token = context.bind(tenant, record=False) if tenant else None
        try:
            async with Client(build_server()) as c:
                return await fn(c)
        finally:
            if token:
                context.unbind(token)
    return anyio.run(go)


# ------------------------------------------------------------------ the tool
def test_graph_schema_counts_are_engine_exact_and_read_only(db):
    async def call(c):
        return (await c.call_tool("graph_schema", {})).structured_content
    out = _session(call, "acme")
    assert "error" not in out, out
    assert out["template"] == "Q-SCHEMA-1+Q-SCHEMA-2+Q-SCHEMA-3+Q-SCHEMA-4" and "GRAPH.RO_QUERY" in out["served_by"] and "tenant_acme" in out["served_by"]
    assert [q["template"] for q in out["queries"]] == ["Q-SCHEMA-1", "Q-SCHEMA-2", "Q-SCHEMA-3", "Q-SCHEMA-4"]
    assert not any(q["truncated"] for q in out["queries"]) and out["complete"]["pairs"] and out["complete"]["keys"]
    g = db.select_graph("tenant_acme")
    labels = {x["label"]: x for x in out["rows"]}
    for lab in ("Service", "Deploy", "Person"):  # db.meta.stats == a full count
        assert labels[lab]["n"] == g.ro_query(f"MATCH (n:{lab}) RETURN count(n)").result_set[0][0]
    assert {"id", "tier"} <= {k["key"] for k in labels["Service"]["keys"]}
    assert any(i["property"] == "name" and "FULLTEXT" in i["types"] for i in labels["Service"]["indexes"])
    rels = {x["type"]: x for x in out["relationships"]}
    prop = g.ro_query("MATCH ()-[r:PROPAGATES_TO]->() RETURN count(r)").result_set[0][0]
    assert rels["PROPAGATES_TO"]["n"] == prop == sum(p["n"] for p in rels["PROPAGATES_TO"]["pairs"])
    assert {"src": "Service", "dst": "Service"} in [{k: p[k] for k in ("src", "dst")} for p in rels["PROPAGATES_TO"]["pairs"]]
    assert "Node" not in labels  # the base label is structural, not reported as a domain label


def test_graph_schema_is_tenant_bound():
    async def call(c):
        return (await c.call_tool("graph_schema", {})).structured_content
    acme, globex = _session(call, "acme"), _session(call, "globex")
    assert "tenant_acme" in acme["served_by"] and "tenant_globex" in globex["served_by"]
    assert acme["totals"]["nodes"] != globex["totals"]["nodes"]


# ------------------------------------------------------------------ resources and prompts (in-memory session)
def test_resources_are_listed_and_tenant_bound():
    async def go(c):
        uris = sorted(str(r.uri) for r in (await c.list_resources()).resources)
        schema = json.loads((await c.read_resource("faultline://schema")).contents[0].text)
        queries = json.loads((await c.read_resource("faultline://queries")).contents[0].text)
        weights = (await c.read_resource("faultline://weights")).contents[0].text
        return uris, schema, queries, weights
    uris, schema, queries, weights = _session(go, "globex")
    assert uris == ["faultline://queries", "faultline://schema", "faultline://weights"]
    assert schema["tenant"] == "globex" and schema["graph"] == "tenant_globex" and "GRAPH.RO_QUERY" in schema["served_by"]
    assert {x["label"] for x in schema["labels"] if x["n"]} >= {"Service", "Deploy"}
    assert any(q["id"] == "Q-GATE-1" for q in queries["templates"])
    assert "flow_slack" in weights


def test_prompts_are_listed_and_rendered():
    async def go(c):
        names = sorted(p.name for p in (await c.list_prompts()).prompts)
        r = await c.get_prompt("investigate_incident", {"symptom": "checkout errors"})
        return names, r.messages[0].content.text
    names, text = _session(go, "acme")
    assert names == ["ask_brain", "investigate_incident", "preflight_pr"]
    assert "checkout errors" in text and "no path, no claim" in text and "causal_paths" in text


# ------------------------------------------------------------------ HTTP: the bearer key decides the tenant
def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


KEYS = {"schema-key-acme-0123456789abcdef": "acme", "schema-key-globex-0123456789abcd": "globex"}


@pytest.fixture(scope="module")
def http_server():
    import uvicorn

    from faultline.mcp_server.http import build_http_app

    port = _port()
    url = f"http://127.0.0.1:{port}"
    app, _ = build_http_app(KEYS, public_url=url, per_min=60)
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


async def _read_schema(url: str, key: str):
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async with create_mcp_http_client(headers={"Authorization": f"Bearer {key}"}) as http:
        async with Client(streamable_http_client(f"{url}/mcp", http_client=http)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            prompts = {p.name for p in (await c.list_prompts()).prompts}
            return names, prompts, json.loads((await c.read_resource("faultline://schema")).contents[0].text)


def test_schema_resource_over_http_follows_the_key(http_server):
    for key, tenant in KEYS.items():
        names, prompts, schema = anyio.run(_read_schema, http_server, key)
        assert "graph_schema" in names and "preflight_pr" in prompts  # hosted (read-only) surface
        assert schema["tenant"] == tenant and schema["graph"] == f"tenant_{tenant}"


# ------------------------------------------------------------------ drift check
def test_drift_check_passes_on_the_live_tenant_graphs():
    from importlib import util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_drift.py"
    spec = util.spec_from_file_location("check_schema_drift", path)
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--tenant", "acme", "--tenant", "globex"]) == 0


def test_drift_check_fails_loudly_on_an_undeclared_label_and_type():
    db = gclient.engine()
    name = scratch_graph("acme", f"drift_{uuid.uuid4().hex[:8]}")
    try:
        db.select_graph(name).query("CREATE (:Node:Service {id:'s1'})-[:HAUNTS]->(:Node:Ghost {id:'g1'})")
        live = {"tenant_acme": introspect(RO("acme"))[0], name: introspect(RO("acme", name))[0]}
        rep = drift(live)
        assert not rep["ok"]
        assert rep["graphs"][name] == {"undeclared_labels": ["Ghost"], "undeclared_rels": ["HAUNTS"]}
        assert rep["graphs"]["tenant_acme"] == {"undeclared_labels": [], "undeclared_rels": []}
    finally:
        gcopy.delete_if_exists(db, name)
