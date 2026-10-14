"""Live (M12): the company brain over time on the seeded graphs. Ownership history (OWNED_AT), as-of beliefs,
component timelines and knowledge health, each a FalkorDB template whose answer changes with the time asked about."""

import pytest

from faultline.brain.ask import ask
from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live

HANDOVER = 1785974400000   # fraud-detection moves from team-payments to team-platform (org_gen, seed 42)
ANCHOR = 1792022400000


@pytest.fixture(scope="module")
def acme(db):
    try:
        RO("acme").require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"acme not seeded: {e}")
    tok = context.bind("acme")
    yield
    context.unbind(tok)


def test_owner_at_changes_with_time_and_names_who_held_the_context(acme):
    before = T.owner_at(target_id="fraud-detection", at=HANDOVER - 1)
    after = T.owner_at(target_id="fraud-detection", at=HANDOVER)
    assert (before["owner_then"], before["owner_now"], before["changed_hands"]) == ("team-payments", "team-platform", True)
    assert (after["owner_then"], after["changed_hands"]) == ("team-platform", False)
    knew = [p["person"] for p in before["knew_it_then"]]
    assert knew and knew[0] == "p-004" and after["knew_it_then"] == []   # most commits first; only after a handover
    assert before["template"] == "Q-OWN-AT" and "OWNED_AT" in before["cypher"]


def test_owner_at_by_incident_reads_the_onset_from_the_graph(acme):
    by_inc = T.owner_at(target_id="fraud-detection", incident_id="inc-h002")
    assert by_inc["owner_then"] == "team-payments" and by_inc["at"] < HANDOVER
    assert "error" in T.owner_at(target_id="fraud-detection")                       # no time anchor: refuse
    assert "error" in T.owner_at(target_id="fraud-detection", incident_id="inc-none")
    assert T.owner_at(target_id="no-such-node", at=ANCHOR)["owner_then"] is None


def test_beliefs_at_respects_supersession_and_ownership_windows(acme):
    early = T.beliefs_at(target_id="product-catalog", at=1760000000000)["rows"][0]
    late = T.beliefs_at(target_id="product-catalog", at=ANCHOR)["rows"][0]
    assert early["decisions"] == ["ADR-009"] and late["decisions"] == ["ADR-021"]      # ADR-021 supersedes ADR-009
    assert early["runbooks"] == [] and late["runbooks"] == ["rb-catalog-lock"]          # not yet written
    assert T.beliefs_at(target_id="fraud-detection", incident_id="inc-h002")["rows"][0]["owner"] == ["team-payments"]


def test_timeline_merges_every_kind_in_time_order(acme):
    r = T.component_timeline(target_id="fraud-detection")
    kinds = {x["kind"] for x in r["rows"]}
    assert {"deploy", "incident", "owner"} <= kinds and r["counts"]["incident"] == 6   # engine bug #9 would drop these
    ats = [x["at"] for x in r["rows"]]
    assert ats == sorted(ats, reverse=True)
    window = T.component_timeline(target_id="fraud-detection", since=HANDOVER, until=ANCHOR)
    assert window["rows"] and all(HANDOVER <= x["at"] <= ANCHOR for x in window["rows"])


def test_knowledge_health_finds_stale_runbooks_and_unrecorded_handovers(acme):
    r = T.knowledge_health(now=ANCHOR)
    found = {(f["kind"], f["id"]) for f in r["rows"]}
    assert ("stale_runbook", "accounting") in found                                  # rb-kafka-lag, 93 days
    assert {("handover_without_runbook", "fraud-detection"), ("handover_without_runbook", "ad")} <= found
    fd = next(f for f in r["rows"] if f["id"] == "fraud-detection")
    assert fd["owner"] == "team-platform" and fd["ref"] == "team-payments" and "p-004" in fd["ask"]
    fresh = T.knowledge_health(now=1783987200000 + 86_400_000)["rows"]                  # a day after rb-kafka-lag's review
    assert ("stale_runbook", "accounting") not in {(f["kind"], f["id"]) for f in fresh}


def test_globex_handover_with_nobody_left_who_worked_on_it(db):
    tok = context.bind("globex")
    try:
        rows = T.knowledge_health(now=ANCHOR)["rows"]
    finally:
        context.unbind(tok)
    ab = next(f for f in rows if f["id"] == "address-book")
    assert ab["kind"] == "handover_without_runbook" and ab["ask"] == [] and "nobody" in ab["why"]


@pytest.mark.parametrize("q,intent,must", [
    ("Who owned fraud-detection during inc-h002?", "owner_then", ["[team-payments]", "[team-platform]", "[p-004]"]),
    ("What did we know about product-catalog as of 2025-11-01?", "asof", ["[ADR-009]"]),
    ("What is the history of fraud-detection?", "history", ["[inc-h040]"]),
    ("Where is our knowledge stale?", "knowledge", ["[fraud-detection]", "[rb-kafka-lag]"]),
])
def test_brain_answers_time_questions_and_passes_the_citation_guard(acme, q, intent, must):
    a = ask(q, "acme")
    assert a.intent == intent and a.guard["ok"], a.answer
    assert all(m in a.answer for m in must), a.answer


def test_hidden_coupling_finds_co_failure_without_a_failure_path(acme):
    r = T.hidden_coupling()
    pairs = {(x["cause"], x["hit"]): x for x in r["rows"]}
    assert {("queue", "accounting"), ("queue", "fraud-detection"), ("recommendation", "product-catalog")} <= set(pairs)
    assert ("payment", "checkout") not in pairs                     # co-fails, but the path exists: nothing missing
    x = pairs[("recommendation", "product-catalog")]
    assert x["co_failures"] >= 3 and x["adjacent"] and "PROPAGATES_TO recommendation → product-catalog" in x["suggest"]
    only = T.hidden_coupling(component_ids=["queue"])["rows"]
    assert only and all("queue" in (y["cause"], y["hit"]) for y in only)
    assert "error" in T.hidden_coupling(min_incidents=1)
    kinds = {(f["kind"], f["id"], f["ref"]) for f in T.knowledge_health(now=ANCHOR)["rows"]}
    assert ("missing_edge", "recommendation", "product-catalog") in kinds


def test_brain_blast_answer_adds_history_only_coupling(acme):
    a = ask("What breaks if recommendation goes down?", "acme")
    assert a.guard["ok"] and "[product-catalog]" in a.answer and "missing edge" in a.answer
    b = ask("What breaks if payment goes down?", "acme")
    assert b.guard["ok"] and "missing edge" not in b.answer


def test_find_entities_unions_full_text_and_vector_seeds(acme):
    r = T.find_entities(text="kafka consumer lag")
    by = {x["id"]: x for x in r["rows"]}
    assert set(by["rb-kafka-lag"]["via"]) == {"fulltext", "vector"}           # found by name and by meaning
    assert any(x["label"] == "Incident" and x["via"] == ["vector"] for x in r["rows"])  # past incidents by meaning only
    assert "Q-FIND-INCIDENT-VEC" in r["template"] and "Q-FIND-SERVICE" in r["template"]
    assert T.find_entities(text="quantum router")["rows"] == []              # below the similarity floor: nothing
    only = T.find_entities(text="payment", labels=["Service"])
    assert only["rows"] and all(x["via"] == ["fulltext"] for x in only["rows"])  # explicit labels: no vector seed
