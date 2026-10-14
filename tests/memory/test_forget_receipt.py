"""Live S10: forgetting a document flips the answer, with a receipt.

Ask → dry run (counts + token) → stale token refused → execute with the token → receipt in audit_acme with exact
counts → the forgotten vectors no longer come back from the index → the same question no longer cites what was
forgotten. The tenant graph is restored from golden afterwards (re-arm keeps the audit graph)."""

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.brain.ask import ask
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.memory import forget

pytestmark = pytest.mark.live


@pytest.fixture
def restore():
    yield
    gcopy.rearm(client.engine(), "acme", reason="test-forget")


def test_s10_answer_flips_with_receipt(restore):
    q = "What did we decide about catalog db migrations?"
    before = ask(q, "acme")
    assert "[ADR-021]" in before.answer and before.guard["ok"]
    plan = forget.dry_run("acme", "doc-adr-021")
    assert [o["id"] for o in plan["owned"]] == ["ADR-021"] and plan["nodes"] == 2
    with pytest.raises(PermissionError):
        forget.execute("acme", "doc-adr-021", "0" * 64, "p-030")
    rec = forget.execute("acme", "doc-adr-021", plan["token"], "p-030")
    assert rec["nodes"] == 2 and rec["forgotten_ids"] == ["ADR-021"] and rec["proof"]["vector_requery"] == "none found"
    audit = client.engine().select_graph("audit_acme").ro_query(
        "MATCH (r:ForgetReceipt {doc:'doc-adr-021', token:$t}) RETURN r.nodes, r.relationships", {"t": plan["token"]}).result_set
    assert audit and audit[0][0] == 2
    after = ask(q, "acme")
    assert "ADR-021" not in after.answer and "[ADR-009]" in after.answer and "not documented" in after.answer
    assert after.guard["ok"]


def test_forgetting_a_runbook_removes_its_vector(restore):
    plan = forget.dry_run("acme", "doc-rb-payment-errors")
    assert plan["vectors"] == 1
    rec = forget.execute("acme", "doc-rb-payment-errors", plan["token"], "p-030")
    assert rec["vectors"] == 1 and rec["vectors_still_found"] == 0


def test_forget_api_dry_run_then_execute(restore):
    api._rate.clear()
    with TestClient(api.app) as c:
        d = c.post("/api/memory/forget", json={"doc_id": "doc-adr-004"}).json()
        assert d["dry_run"] and len(d["token"]) == 64
        assert c.post("/api/memory/forget", json={"doc_id": "doc-adr-004", "token": d["token"]}).status_code == 422
        r = c.post("/api/memory/forget", json={"doc_id": "doc-adr-004", "token": d["token"], "approver": "p-030"})
        assert r.status_code == 200 and not r.json()["dry_run"]
        assert c.post("/api/memory/forget", json={"doc_id": "doc-nope"}).status_code == 404
