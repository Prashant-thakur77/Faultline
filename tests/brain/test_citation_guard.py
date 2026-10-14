"""Live: company brain answers cite only ids its own tool calls saw; the citation guard (a read-only query)
refuses anything else."""

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.brain.ask import ask, citation_guard

pytestmark = pytest.mark.live


@pytest.mark.parametrize("q,intent,must_cite", [
    ("Who on the team has worked on payment before?", "people", {"payment"}),
    ("What did we decide about payment timeouts, and is it still current?", "decision", {"ADR-012"}),
    ("Which revenue-path services lack a runbook or owner?", "gaps", set()),
    ("What breaks if productcatalog goes down?", "blast", {"product-catalog", "checkout", "frontend"}),
])
def test_on_camera_questions_are_cited_and_guarded(q, intent, must_cite):
    a = ask(q, "acme")
    assert a.intent == intent and a.tier == 2
    assert a.guard["ok"] and a.citations and must_cite <= set(a.citations)
    assert all(s["template"] for s in a.steps if not s["error"])


def test_superseded_decision_points_to_its_head():
    a = ask("What did we decide about catalog db migrations?", "acme")
    assert "[ADR-009]" in a.answer and "superseded; the current decision is [ADR-021]" in a.answer


def test_guard_refuses_ids_not_seen_this_run():
    a = ask("Who has worked on payment?", "acme")
    ok = citation_guard("acme", a.run_id, "Ask [p-017] about [payment].")
    assert ok["ok"]
    bad = citation_guard("acme", a.run_id, "Ask [p-017]; also [ADR-021] decided it.")  # ADR-021 never seen in this run
    assert not bad["ok"] and bad["unseen"] == ["ADR-021"]
    other = ask("What breaks if cart goes down?", "acme")  # ids seen by ANOTHER question do not count
    assert not citation_guard("acme", other.run_id, "[p-017]")["ok"]


def test_brain_api():
    api._rate.clear()
    with TestClient(api.app) as c:
        r = c.post("/api/brain/ask", json={"question": "Which revenue-path services lack a runbook or owner?"})
        assert r.status_code == 200 and r.json()["guard"]["ok"]
        assert c.post("/api/brain/ask", json={"question": "x"}).status_code == 422


def test_session_history_persists_and_drives_follow_ups():
    """T2: turns persist in the graph; a follow-up with no entity resolves to the component of the previous answer
    (read back via session_history), and history survives a new session."""
    import uuid

    user = f"u-{uuid.uuid4().hex[:6]}"
    first = ask("What breaks if productcatalog goes down?", "acme", user=user, session=f"{user}-s1")
    follow = ask("And who has worked on it?", "acme", user=user, session=f"{user}-s2")  # a NEW session
    assert "[product-catalog]" in follow.answer and follow.guard["ok"]
    assert any(s["tool"] == "session_history" for s in follow.steps)
    from faultline.graph.ro import RO

    turns = RO("acme").run("Q-SESS-1", {"user": user}).rows
    # session ids are server-issued (review round 4, M1): a supplied id is validated and prefixed with sess-
    assert {t["session"] for t in turns} == {f"sess-{user}-s1", f"sess-{user}-s2"} and len(turns) == 4
    assert first.session == f"sess-{user}-s1"
    from faultline.graph import client

    client.engine().select_graph("tenant_acme").query(
        "MATCH (s:Session {user:$u})-[:HAS_TURN]->(t:Turn) DETACH DELETE s, t", {"u": user})


def test_asking_about_an_id_does_not_make_it_citable():
    """A tool's `about` ids are what its evidence is ABOUT, not what the graph returned: asking a timeline for a
    decision id that is not a component returns nothing, so the id must not become SAW and citable (review M12)."""
    import uuid

    from faultline.brain.ask import _Session
    from faultline.graph import client, writes
    from faultline.graph.tenant import tenant_graph

    run = f"brain-test-{uuid.uuid4().hex[:8]}"
    writes.open_brain_run(client.engine().select_graph(tenant_graph("acme")), run=run, tenant="acme", question="probe")
    s = _Session("acme", run)
    r = s.call("component_timeline", target_id="ADR-021")
    assert not any(x["ref"] == "ADR-021" for x in r["rows"])
    assert not citation_guard("acme", run, "It was decided in [ADR-021].")["ok"]
    s.call("decisions_about", target_id="product-catalog")       # now the graph returns it
    assert citation_guard("acme", run, "It was decided in [ADR-021].")["ok"]
