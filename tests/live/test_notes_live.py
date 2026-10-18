"""Live: shared agent notes (T2), FalkorDB-backed memory that several agents write and read.

remember → W-NOTE-1 (one atomic query: components exist, reply target exists, daily quota on the engine clock);
recall_notes → Q-NOTE-RECALL (one read-only query: vector similarity ∪ PROPAGATES_TO neighbourhood, ranked in the
engine by faultline.noteScore). A note is a lead, never evidence: nothing in it may ground the gate's G1.
"""

from __future__ import annotations

import threading
import uuid

import pytest

from faultline.agent.weights import weights
from faultline.graph import client, udf
from faultline.graph.templates import catalogue
from faultline.mcp_server import context
from faultline.mcp_server import tools as T
from faultline.memory import notes

pytestmark = pytest.mark.live


@pytest.fixture
def acme(db):
    udf.load_udfs(db.connection)
    notes.ensure_memory_graph("acme")
    tok = context.bind("acme")
    made: list[str] = []
    yield made
    context.unbind(tok)
    db.select_graph("agentmem_acme").query("MATCH (n:Note) WHERE n.id IN $ids DETACH DELETE n", {"ids": made})


def _note(made: list[str], **kw) -> dict:
    out = T.remember(**kw)
    assert "error" not in out, out
    made.append(out["id"])
    return out


def test_a_note_is_recalled_by_meaning_and_by_graph_distance(acme):
    tag = uuid.uuid4().hex[:6]
    a = _note(acme, text=f"payment p99 doubled right after the config push {tag}; not proven", about=["payment"],
              agent_name="claude-desktop")
    b = _note(acme, text=f"checkout 5xx line up with payment timeouts {tag}", about=["checkout"], kind="observation",
              agent_name="oncall-bot", reply_to=a["id"], stance="confirms")
    near = T.recall_notes(text=f"payment timeouts after a config push {tag}", focus_id="checkout")  # both routes
    rows = {r["id"]: r for r in near["rows"]}
    assert near["template"] == "Q-NOTE-RECALL" and rows[b["id"]]["hops"] == 0 and rows[a["id"]]["hops"] == 1
    assert [r["score"] for r in near["rows"]] == sorted((r["score"] for r in near["rows"]), reverse=True)
    assert {"agent": "local", "stance": "confirms"}.items() <= rows[a["id"]]["replies"][0].items()
    by_meaning = T.recall_notes(text="payment latency went up after a configuration change")
    assert a["id"] in [r["id"] for r in by_meaning["rows"]]
    floor = float(weights()["notes"]["min_similarity"])
    assert all(r["similarity"] >= floor for r in by_meaning["rows"] if r["hops"] is None)


def test_a_note_never_grounds_a_claim(acme):
    assert catalogue()["Q-NOTE-RECALL"].seen == ()          # no `seen` column: G1 cannot be satisfied by a note
    _note(acme, text="the cause is surely payment", about=["payment"], kind="hypothesis")
    out = T.recall_notes(focus_id="payment")
    assert out["rows"] and "payment" in out["rows"][0]["about"]
    assert not out.get("grounded_ids")                      # the envelope passes no `about`: nothing is marked SAW


def test_refusals_come_from_the_graph(acme):
    assert "not in this graph" in T.remember(text="a note about nothing", about=["no-such-component"])["error"]
    assert "to reply to" in T.remember(text="a reply to nothing", about=["payment"], reply_to="note-000000000000")["error"]
    assert T.remember(text="x", about=["payment"])["error"].startswith("invalid arguments")
    assert T.remember(text="a note", about=["payment"], kind="order")["error"].startswith("invalid arguments")
    assert T.recall_notes()["error"].startswith("invalid arguments")


def test_expired_notes_are_not_recalled(acme, monkeypatch):
    monkeypatch.setitem(weights()["notes"], "ttl_days", 1e-9)          # expires on the engine clock at once
    gone = _note(acme, text=f"a short-lived note {uuid.uuid4().hex[:6]}", about=["cart"])
    monkeypatch.setitem(weights()["notes"], "ttl_days", 7)
    assert gone["id"] not in [r["id"] for r in T.recall_notes(focus_id="cart")["rows"]]


def test_the_daily_quota_is_atomic_under_concurrent_writers(acme, monkeypatch):
    monkeypatch.setitem(weights()["notes"], "quota_per_day", 5)
    principal = f"quota-test-{uuid.uuid4().hex[:6]}"
    ok, refused, lock = [], [], threading.Lock()

    def write(i: int) -> None:
        try:
            out = notes.remember("acme", principal=principal, text=f"concurrent note {i}", about=["email"])
            with lock:
                ok.append(out["id"])
        except notes.NoteRefused as e:
            with lock:
                refused.append(str(e))

    threads = [threading.Thread(target=write, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    acme.extend(ok)
    assert len(ok) == 5 and len(refused) == 11 and all("quota" in m for m in refused)
    used = client.engine().select_graph("agentmem_acme").ro_query(
        "MATCH (:Author {id: $p})-[:WROTE]->(n:Note) RETURN count(n)", {"p": principal}).result_set[0][0]
    assert used == 5


def test_the_public_demo_stays_read_only_unless_a_host_opts_in(monkeypatch):
    from faultline.config import settings
    from faultline.mcp_server import resources
    from faultline.mcp_server.server import WRITE_TOOLS, register_tools

    monkeypatch.setattr(resources, "register", lambda server: None)

    class Srv:
        def __init__(self):
            self.tools = {}

        def add_tool(self, fn, name, **kw):
            self.tools[name] = kw["annotations"]

    monkeypatch.setattr(settings, "faultline_mcp_notes", False)
    hosted = register_tools(Srv(), public=True).tools
    assert "recall_notes" in hosted and not WRITE_TOOLS & set(hosted)
    assert all(a.read_only_hint for a in hosted.values())
    monkeypatch.setattr(settings, "faultline_mcp_notes", True)
    assert register_tools(Srv(), public=True).tools["remember"].read_only_hint is False
