"""Live: the product works with ACL on (prod mode). The read-only user ro_<tenant>, rendered from the exact template
line, can read everything a run needs (tenant, eval clean room, audit ledger) and still nothing of another tenant."""

import secrets
from pathlib import Path

import anyio
import pytest

from faultline import api, scenario
from faultline.agent.loop import BaselineInvestigator
from faultline.config import settings
from faultline.graph import client
from faultline.graph.ro import RO
from faultline.graph.tenant import audit_graph

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]


def _line(tenant: str, pw: str) -> list[str]:
    line = next(ln for ln in (ROOT / "deploy" / "users.acl.template").read_text().splitlines()
                if ln.startswith(f"user ro_{tenant} "))
    return line.replace("${FALKORDB_RO_PASSWORD}", pw).split()[1:]


@pytest.fixture
def acl_on(db, monkeypatch):
    pw = secrets.token_hex(16)
    db.connection.execute_command("ACL", "SETUSER", *_line("acme", pw))
    monkeypatch.setattr(settings, "falkordb_ro_password", pw)
    client.reset_connections()
    yield pw
    client.reset_connections()
    db.connection.execute_command("ACL", "DELUSER", "ro_acme")


def test_a_scenario_runs_end_to_end_with_the_ro_acl_user(acl_on):
    import os

    import redis
    assert "ro_acme" in RO("acme").run("Q-COUNT-1", {}).served_by           # reads really go through the ACL user
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=False))
    assert res.error is None and res.outcome == "CONFIRMED", res.error      # eval clean room readable as ro_acme
    assert api._llm_spend("acme")["usd_last_hour"] >= 0                      # the audit ledger is readable
    RO("acme", audit_graph("acme")).run("Q-LLM-SPEND", {"since": 0})
    with pytest.raises(ValueError):
        RO("acme", "tenant_globex")                                        # the app refuses another tenant's graph …
    raw = redis.Redis(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379")),
                      username="ro_acme", password=acl_on)
    with pytest.raises(redis.exceptions.ResponseError, match="(?i)nopermission|no permissions"):  # … and the ACL
        raw.execute_command("GRAPH.RO_QUERY", "tenant_globex", "MATCH (n) RETURN count(n)")
    raw.close()
