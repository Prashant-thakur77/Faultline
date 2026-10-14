"""Live: our RO client path works under a minimal ACL user and cannot write or cross tenants."""

import uuid

import pytest

from faultline.config import settings
from faultline.graph import client
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.fixture
def acl_user(db, monkeypatch):
    pw = uuid.uuid4().hex
    tenant = "acltest"
    conn = db.connection
    conn.execute_command("ACL", "SETUSER", f"ro_{tenant}", "on", f">{pw}", "resetkeys", "resetchannels", "-@all",
                         "+GRAPH.RO_QUERY", "+GRAPH.EXPLAIN", "+PING", "+HELLO", "+CLIENT|SETNAME", "+CLIENT|SETINFO",
                         f"~tenant_{tenant}", f"~scratch_{tenant}_*")
    db.select_graph(f"tenant_{tenant}").query("CREATE (:Meta {id:'meta', ready:true, data_hash:'x', engine:'t'})")
    db.select_graph("tenant_other").query("CREATE (:Meta {id:'meta', ready:true})")
    monkeypatch.setattr(settings, "falkordb_ro_password", pw)
    client.reset_connections()
    yield tenant
    client.reset_connections()
    conn.execute_command("ACL", "DELUSER", f"ro_{tenant}")
    for g in (f"tenant_{tenant}", "tenant_other"):
        db.select_graph(g).delete()


def test_ro_user_reads_own_tenant(acl_user):
    r = RO(acl_user).require_ready()
    assert r["ready"] is True


def test_ro_user_cannot_write(acl_user):
    g = client.ro_graph(acl_user)
    with pytest.raises(Exception):
        g.query("CREATE (:X)")


def test_ro_user_cannot_read_other_tenant(acl_user):
    # layer 1: the wrapper refuses a graph that is not the bound tenant's
    with pytest.raises(ValueError):
        RO(acl_user, graph_name="tenant_other")
    # layer 2: even a raw handle on the RO connection is denied by the database ACL
    from falkordb import Graph

    raw = Graph(client._ro_redis(acl_user), "tenant_other")
    with pytest.raises(Exception, match="(?i)perm|access|no permissions"):
        raw.ro_query("MATCH (n) RETURN count(n)")
