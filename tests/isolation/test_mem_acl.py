"""S7 for shared agent notes (T2): FalkorDB's ACL, not our code, keeps a note away from the graph the gate reads.

mem_<tenant> may run GRAPH.QUERY on exactly one key, agentmem_<tenant>; ro_<tenant> may read that graph but not write
it. The exact rules shipped in deploy/users.acl.template are applied to throwaway users (a configured user is never
touched); with FALKORDB_MEM_PASSWORD set (judge-check's acl_ephemeral run), the configured mem_acme user is checked
end to end through the product's own write path.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import redis
from falkordb import Graph

from faultline.config import settings
from faultline.graph import client
from faultline.memory import notes

ROOT = Path(__file__).resolve().parents[2]
NOPERM = "(?i)NOPERM|no permissions"


def _rules(user: str) -> list[str]:
    line = next(ln for ln in (ROOT / "deploy" / "users.acl.template").read_text().splitlines()
                if ln.startswith(f"user {user} "))
    return line.split()[2:]


@pytest.fixture
def throwaway(db):
    """Make a throwaway user from a template rule; yield a connect(rule_user) → redis.Redis factory."""
    made: list[str] = []
    conns: list[redis.Redis] = []
    notes.ensure_memory_graph("acme")
    notes.ensure_memory_graph("globex")

    def make(template_user: str) -> redis.Redis:
        user, pw = f"s7_{template_user}_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
        rules = [f">{pw}" if r.startswith(">") else r for r in _rules(template_user)]
        try:
            db.connection.execute_command("ACL", "SETUSER", user, "reset", *rules)
        except redis.ResponseError as e:
            pytest.skip(f"cannot provision a throwaway ACL user here: {e}")
        made.append(user)
        c = redis.Redis(host=settings.falkordb_host, port=settings.falkordb_port, username=user, password=pw,
                        single_connection_client=True, socket_timeout=10)
        conns.append(c)
        return c

    yield make
    for c in conns:
        c.close()
    for u in made:
        db.connection.execute_command("ACL", "DELUSER", u)


def test_mem_rule_writes_its_memory_graph_and_nothing_else(throwaway, db):
    rules = _rules("mem_acme")
    assert "~agentmem_acme" in rules and [r for r in rules if r.startswith("~")] == ["~agentmem_acme"]
    c = throwaway("mem_acme")
    probe = f"s7-probe-{uuid.uuid4().hex[:8]}"
    Graph(c, "agentmem_acme").query("CREATE (:S7Probe {id: $id})", {"id": probe})          # its own key: allowed
    try:
        for graph, query in [("tenant_acme", "MATCH (n) RETURN count(n)"),                    # the gate's graph
                             ("tenant_acme", "CREATE (:S7Probe {id: 'x'})"),
                             ("golden_acme", "MATCH (n) RETURN count(n)"),
                             ("agentmem_globex", "MATCH (n) RETURN count(n)")]:              # another tenant's notes
            with pytest.raises(redis.ResponseError, match=NOPERM):
                Graph(c, graph).query(query)
        for cmd in (("GRAPH.DELETE", "agentmem_acme"), ("GRAPH.COPY", "agentmem_acme", "agentmem_acme_x"),
                    ("GRAPH.CONFIG", "GET", "TIMEOUT"), ("ACL", "WHOAMI"), ("GRAPH.LIST",)):
            with pytest.raises(redis.ResponseError, match=NOPERM):
                c.execute_command(*cmd)
    finally:
        db.select_graph("agentmem_acme").query("MATCH (p:S7Probe {id: $id}) DELETE p", {"id": probe})


def test_ro_rule_reads_the_memory_graph_but_cannot_write_it(throwaway):
    assert "~agentmem_acme" in _rules("ro_acme")
    c = throwaway("ro_acme")
    Graph(c, "agentmem_acme").ro_query("MATCH (n:Note) RETURN count(n)")                     # read: allowed
    with pytest.raises(redis.ResponseError, match=NOPERM):
        Graph(c, "agentmem_acme").query("CREATE (:S7Probe {id: 'x'})")


def test_configured_mem_user_writes_notes_and_is_refused_on_the_tenant_graph(db):
    if not client.mem_acl_enabled():
        pytest.skip("FALKORDB_MEM_PASSWORD is unset here, so notes are written by the engine user (dev); the shipped "
                    "rule is checked by test_mem_rule_writes_its_memory_graph_and_nothing_else")
    out = notes.remember("acme", principal="s7-test", text="s7: a note written through the mem_acme ACL user",
                         about=["payment"], kind="observation")
    try:
        assert out["graph"] == "agentmem_acme"
        raw = client.mem_graph("acme")
        with pytest.raises(redis.ResponseError, match=NOPERM):
            Graph(raw.client, "tenant_acme").query("MATCH (n) RETURN count(n)")
    finally:
        db.select_graph("agentmem_acme").query("MATCH (n:Note {id: $id}) DETACH DELETE n", {"id": out["id"]})
