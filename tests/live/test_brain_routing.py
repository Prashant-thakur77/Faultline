"""Live: the brain's two-stage router. Stage 1 is the keyword router; when none of its patterns matches, stage 2 routes
in FalkorDB (route_question → Q-BRAIN-INTENT over seeded IntentExemplar nodes).

* both golden graphs carry the exemplars with a vector and a full-text index on them (`make seed`);
* the graph stage on its own also routes each kind (route_question called directly);
* `Answer.route.stage` says which stage routed a question, and the graph is asked only when no keyword matched;
* off-topic questions (no keyword) are refused by the graph stage ("I can't answer that from the graph") with nothing cited, and the citation guard
  is untouched: exemplar ids are never "seen", so an answer citing one is withheld.
Questions run in a clean room (a GRAPH.COPY of golden_<t>), like the brain eval.
"""

from __future__ import annotations

import uuid

import pytest

from faultline.brain import ask as A
from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.graph.tenant import golden_graph
from faultline.ingest import brain_intents
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def room():
    db = client.engine()
    name = f"eval_acme_braintest_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, golden_graph("acme"), name)
    yield name
    gcopy.delete_if_exists(db, name)


def _route(tenant: str, q: str) -> dict:
    tok = context.bind(tenant, graph=golden_graph(tenant), record=False)
    try:
        return T.route_question(text=q)
    finally:
        context.unbind(tok)


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_every_golden_graph_has_the_exemplars_and_both_indexes(tenant):
    g = client.engine().select_graph(golden_graph(tenant))
    n = g.ro_query("MATCH (x:IntentExemplar) WHERE x.embedding IS NOT NULL RETURN count(x)").result_set[0][0]
    assert n == len(brain_intents.exemplars())
    types = next(dict(r[1]) for r in g.ro_query("CALL db.indexes() YIELD label, types RETURN label, types").result_set
                 if r[0] == "IntentExemplar")
    assert "VECTOR" in types["embedding"] and "FULLTEXT" in types["text"] and "RANGE" in types["id"]


@pytest.mark.parametrize("q,kind", [
    ("Who has knowledge of payment?", "people"),                  # not a knowledge-health question
    ("Who is the owner on call for checkout?", "people"),         # "owner on" alone is not the past
    ("Who was the owner of ad on 2026-06-01?", "owner_then"),
    ("Who owned fraud-detection during inc-h002?", "owner_then"),
    ("Where is our knowledge stale?", "knowledge"),
    ("What is the history of payment?", "history"),
    ("Which customers are affected if checkout goes down?", "obligations"),
    ("What SLOs depend on payment?", "obligations"),
    ("How much revenue at risk if cart fails?", "obligations"),
    ("What breaks if payment goes down?", "blast"),
    ("Who has worked on stg_customers?", "people"),               # a table name is not a customer question
    ("What did we decide about customer emails?", "decision"),
])
def test_the_graph_stage_alone_routes_each_kind(q, kind):
    r = _route("acme", q)
    assert r["routed"] == kind, (q, r["rows"][:2])
    assert r["mode"] == "vector+fulltext" and r["evidence_id"].startswith("ev_")


def test_globex_routes_with_the_same_exemplars():
    assert _route("globex", "What breaks if ledger-service goes down?")["routed"] == "blast"
    assert _route("globex", "Which customers are affected if order-orchestrator fails?")["routed"] == "obligations"


@pytest.mark.parametrize("q", ["What is the stock price of a fruit company?", "How do I bake sourdough bread?",
                               "Please restart the checkout pods", "Good afternoon!"])
def test_off_topic_questions_are_refused_with_nothing_cited(room, q):
    a = A.ask(q, "acme", graph=room)
    assert a.intent == "none" and a.answer.startswith(A.REFUSAL), a.answer
    assert a.citations == [] and a.guard["ok"]
    # a request to act or small talk is refused at once; a weak match first asks the documents (one read-only query,
    # Q-KNOW-1), which must agree by words AND meaning before the brain answers from them: here they do not
    searched = not a.route["best"]["refuse"]
    assert [s["tool"] for s in a.steps] == [A.ROUTE_TOOL] + (["search_knowledge"] if searched else [])
    assert a.tier == (2 if searched else 1)
    assert a.route["stage"] == "graph" and a.route["routed"] is None and a.route["best"]["intent"]


def test_a_keyword_match_never_asks_the_graph_router(room):
    a = A.ask("What breaks if payment goes down?", "acme", graph=room)
    assert a.intent == "blast" and a.route == {"stage": "keyword", "routed": "blast", "matched": "breaks"}
    assert A.ROUTE_TOOL not in [s["tool"] for s in a.steps] and {"payment", "checkout"} <= set(a.citations)


def test_a_graph_routed_answer_keeps_the_citation_guard(room):
    a = A.ask("If payment crashes, what else fails?", "acme", graph=room)   # no keyword pattern matches
    assert a.route["stage"] == "graph" and a.intent == "blast"
    assert a.guard["ok"] and {"payment", "checkout"} <= set(a.citations)
    assert a.steps[0]["tool"] == A.ROUTE_TOOL and a.steps[0]["evidence_id"]
    nearest = a.route["best"]["nearest_text"]
    assert nearest  # the exemplar it matched is shown, but its id is never citable:
    xid = next(x["id"] for x in brain_intents.exemplars() if x["text"] == nearest)
    bad = A.citation_guard("acme", a.run_id, f"[payment] and [{xid}]", room)
    assert not bad["ok"] and bad["unseen"] == [xid]
