"""Live: which runbook to follow, who decided, and the past by month, on the seeded acme graph.

* runbooks_about is ONE read-only query (Q-RUNBOOK-ABOUT): a component's own runbooks and its symptoms', the symptom
  kind asked about first, then runbooks one failure hop away;
* trace_decision names who decided a decision and its head (Q-DEC-WHO), so a decision found by name or id has its
  deciders too, not only one found through a component;
* the brain answers those questions with every cited id seen by a tool call (the citation guard passes), in a clean
  room copied from golden_acme.
"""

from __future__ import annotations

import uuid

import pytest

from faultline.brain.ask import ask
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO
from faultline.graph.tenant import golden_graph
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def acme(db):
    try:
        RO("acme").require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"acme not seeded: {e}")
    tok = context.bind("acme")
    yield
    context.unbind(tok)


@pytest.fixture(scope="module")
def room(db):
    name = f"eval_acme_brainrb_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(gclient.engine(), golden_graph("acme"), name)
    yield name
    gcopy.delete_if_exists(gclient.engine(), name)


def test_runbooks_about_ranks_its_own_and_the_named_symptom_first(acme):
    r = T.runbooks_about(component_id="checkout", symptom_kinds=["error_rate"])
    assert r["template"] == "Q-RUNBOOK-ABOUT" and "RUNBOOK_FOR" in r["cypher"]
    direct = [x["id"] for x in r["rows"] if x["dist"] == 0]
    assert {"rb-checkout-degraded", "rb-payment-errors"} <= set(direct)
    assert r["rows"][0]["dist"] == 0 and r["rows"][0]["symptom_named"]
    assert all(x["dist"] == 1 for x in r["rows"][len(direct):])      # one hop away only after the component's own


def test_runbooks_about_reaches_one_failure_hop_when_none_is_written_for_it(acme):
    r = T.runbooks_about(component_id="marts.exec_revenue_metric", symptom_kinds=["kpi_jump"])
    assert [(x["dist"], x["symptom_named"]) for x in r["rows"]][:1] == [(1, True)]
    assert any(c.startswith("sym-kpi_jump") for c in r["rows"][0]["covers"])
    assert T.runbooks_about(component_id="no-such-node")["rows"] == []
    assert "error" in T.runbooks_about(component_id="checkout", symptom_kinds=["x"] * 9)   # bounded input


def test_trace_decision_names_who_decided_it_and_its_head(acme):
    r = T.trace_decision(decision_id="ADR-009")
    assert r["rows"][0]["head"] == "ADR-021" and "Q-DEC-WHO" in r["template"]
    who = {d: {p["person"]: p["active"] for p in ps} for d, ps in r["deciders"].items()}
    assert who["ADR-009"] == {"p-025": False} and {"p-006", "p-016"} <= set(who["ADR-021"])


@pytest.mark.parametrize("q,kind,want", [
    ("Which runbook do I follow when checkout errors spike?", "runbook", {"rb-checkout-degraded", "rb-payment-errors"}),
    ("What should on-call do when the exec revenue KPI jumps?", "runbook", {"kpi.exec_revenue", "rb-derived-32def3f1f2"}),
    ("Who wrote ADR-009 and are they still with us?", "decision", {"ADR-009", "p-025"}),
    ("Who made the call on online migrations for the catalog DB?", "decision", {"ADR-021", "p-006", "p-016"}),
    ("Who owned fraud-detection in August 2026?", "owner_then", {"team-payments", "team-platform"}),
    ("What did we believe about ad on 2026-07-01?", "asof", {"ad", "team-storefront"}),
])
def test_the_brain_answers_with_cited_ids_the_graph_returned(room, q, kind, want):
    a = ask(q, "acme", graph=room)
    assert a.intent == kind and a.guard["ok"], a.answer
    assert want <= set(a.citations), a.answer


@pytest.mark.parametrize("text,want", [("shipping quote calculator", "quote"), ("valkey", "cache"),
                                       ("astronmy db", "astronomy-db"), ("exec revenue kpi", "kpi.exec_revenue"),
                                       ("fct_revenue model", "marts.fct_revenue")])
def test_a_component_resolves_from_the_words_of_its_name_in_one_query(acme, text, want):
    r = T.resolve_entity(text=text, fuzzy=False, by_name=True)
    assert r["template"] == "Q-FIND-NAME" and r["rows"][0]["id"] == want


def test_decisions_about_includes_the_policies_that_govern_it(acme):
    r = T.decisions_about(target_id="payment")
    pol = {p["policy"]: p for p in r["policies"]}
    assert "POL-freeze-payment-weekend" in pol and "Q-POLICY-ABOUT" in r["template"]
    assert [d["person"] for d in pol["POL-freeze-payment-weekend"]["deciders"]] == ["p-004"]


@pytest.mark.parametrize("q,kind,want", [
    ("are there decisions where everyone who decided them has left?", "knowledge", {"ADR-004", "p-019"}),
    ("who put the payment change freeze in place", "decision", {"POL-freeze-payment-weekend", "p-004"}),
    ("which team is on the hook for the shipping quote calculator?", "context", {"quote"}),
    ("if valkey dies what breaks", "blast", {"cache", "cart"}),
    ("is there a runbook for the recs cache stampede thing", "runbook", {"rb-recs-cache"}),
])
def test_the_brain_answers_cycle_two(room, q, kind, want):
    a = ask(q, "acme", graph=room)
    assert a.intent == kind and a.guard["ok"], a.answer
    assert want <= set(a.citations), a.answer
