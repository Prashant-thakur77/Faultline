"""Live: the brain resolves the component a question is about with EXACT id matches across every word pair and word
first, fuzzy (FLEX Jaro-Winkler) only when nothing matched exactly, and never fuzzy on a generic word or a mere
prefix. Each case was a verified false positive before the fix. Tool errors are surfaced, not read as "no match"."""

import pytest

from faultline.brain import ask as A
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.mark.parametrize("tenant,q,want", [
    ("acme", "Check what depends on cart", "cart"),               # was checkout at 0.925 ("check" + fuzzy)
    ("acme", "Which flags affect payment?", "payment"),           # was flagd ("flags" fuzzy)
    ("acme", "What breaks if pyment goes down?", "payment"),      # a real misspelling still resolves fuzzily
    ("globex", "Audit who changed the ledger", "ledger-service"),  # was audit-log
    ("globex", "Which metric dashboards depend on ledger?", "ledger-service"),  # was metrics-api
    ("globex", "What event caused the outage?", None),            # was event-bus
    ("globex", "Is the current policy still current?", None),
])
def test_exact_before_fuzzy_and_no_generic_word_matches(tenant, q, want):
    s = A._Session(tenant, "test-entity-resolution")
    ent = A._entity(s, q)
    assert (ent or {}).get("id") == want


@pytest.mark.parametrize("tenant,word", [("acme", "check"), ("acme", "flags"), ("acme", "current"),
                                         ("globex", "audit"), ("globex", "metric"), ("globex", "event")])
def test_resolve_entity_refuses_generic_words_and_prefixes(tenant, word):
    tok = context.bind(tenant)
    try:
        assert T.resolve_entity(text=word)["rows"] == []
    finally:
        context.unbind(tok)


def test_exact_only_mode_never_runs_the_fuzzy_template():
    tok = context.bind("acme")
    try:
        r = T.resolve_entity(text="pyment", fuzzy=False)
        assert r["rows"] == [] and "Q-FIND-FUZZY" not in r["template"]
    finally:
        context.unbind(tok)


def test_a_tool_error_is_surfaced_not_read_as_no_match(monkeypatch):
    s = A._Session("acme", "test-entity-error")
    monkeypatch.setattr(s, "call", lambda name, **kw: {"error": "GraphError: Unknown function 'flex.text.jaroWinkler'"})
    with pytest.raises(A.BrainToolError, match="jaroWinkler"):
        A._entity(s, "Who has worked on pyment?")
    intent, text, _ = A._baseline(s, "Who has worked on pyment?")
    assert "unavailable" in text and "jaroWinkler" in text and "could not find" not in text
