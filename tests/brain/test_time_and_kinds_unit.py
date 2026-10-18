"""Unit (no FalkorDB): what time a question is about, and the kinds added for runbooks and deciders.

* `_when` reads ISO dates, incident ids, months ("in April 2026", "last June", "March 3, 2026"), ISO months, seasons,
  years and times ago, a period at its first day with the date used in the label; a month name with no preposition,
  day or year is not a time ("who may know");
* the keyword router sends "which runbook" to the runbook kind (a stale or missing runbook stays a knowledge or gap
  question), "made the call / signed off / approved" to decisions, and "who owned / was on call … <time>" to the past;
* entity resolution tries a two-letter word only as an exact id, never fuzzy;
* a decision named by its id is read directly (padded "adr-21" → ADR-021).
"""

from __future__ import annotations

import datetime as dt

import pytest

from faultline.brain import ask as A
from faultline.mcp_server import tools as T

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc).timestamp()


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


@pytest.mark.parametrize("q,at,end", [
    ("Who owned ad on 2026-07-01?", "2026-07-01", None),
    ("Who owned ad in April 2026?", "2026-04-01", "2026-05-01"),
    ("Who owned ad in July?", "2026-07-01", "2026-08-01"),
    ("Who owned ad last June?", "2026-06-01", "2026-07-01"),
    ("Who owned ad in October?", "2026-10-01", "2026-11-01"),        # this month has begun: this year's
    ("Who owned ad last October?", "2025-10-01", "2025-11-01"),      # "last" skips this one
    ("Who owned ad in December?", "2025-12-01", "2026-01-01"),       # not begun yet: last year's
    ("Who owned ad on 3 March 2026?", "2026-03-03", None),
    ("Who owned ad on March 3, 2026?", "2026-03-03", None),
    ("Who owned ad in 2026-02?", "2026-02-01", "2026-03-01"),
    ("Who owned ad in the spring of 2026?", "2026-03-01", "2026-06-01"),
    ("Who owned ad in 2025?", "2025-01-01", "2026-01-01"),
    ("Who owned ad 3 weeks ago?", "2026-09-27", None),
    ("Who owned ad two months ago?", "2026-08-18", None),
    ("Who owned ad last month?", "2026-09-01", "2026-10-01"),
    ("Who owned ad yesterday?", "2026-10-17", None),
])
def test_when_reads_dates_months_periods_and_times_ago(q, at, end):
    w = A._when(q, now=NOW)
    assert _day(w["at"]) == at and (_day(w["end"]) if "end" in w else None) == end
    assert at in w["label"]                                           # the answer says which date it used


@pytest.mark.parametrize("q", ["Who may know cart?", "What breaks if cart fails?", "Who decided ADR-012?",
                               "Is the 2026-02-30 deploy real?"])
def test_when_is_empty_without_a_time(q):
    assert A._when(q, now=NOW) == {}


def test_when_keeps_incident_ids():
    assert A._when("Who owned it during inc-h002?", now=NOW) == {"incident_id": "inc-h002", "label": "inc-h002"}


@pytest.mark.parametrize("q,kind", [
    ("Which runbook should I follow for checkout?", "runbook"),
    ("Is there a playbook for product catalog being slow?", "runbook"),
    ("payment is throwing errors, what should on-call do?", "runbook"),
    ("How do we mitigate cart errors?", "runbook"),
    ("Which runbooks are stale?", "knowledge"),                    # a stale runbook is knowledge health
    ("Which services have no runbook?", "gaps"),                    # a missing runbook is a gap
    ("Who made the call on catalog migrations?", "decision"),
    ("Who signed off on best-effort emails?", "decision"),
    ("Who approved the retry rule?", "decision"),
    ("How are we supposed to handle retries in payment?", "decision"),
    ("Who owned ad last June?", "owner_then"),
    ("Which team was responsible for fraud-detection at the time of inc-h002?", "owner_then"),
    ("Who handled fraud detection back in March 2026?", "owner_then"),
    ("who was on call for payment 3 months ago", "asof"),
    ("What did we believe about ad on 2026-07-01?", "asof"),
    ("Who is on call for checkout?", "people"),                     # no time: now
    ("What relies on cart?", "blast"),
    ("Which service-level objectives rely on payment?", "obligations"),
])
def test_keyword_kinds(q, kind):
    assert A._intent(q) == kind


def test_the_runbook_kind_is_a_composer_kind_and_seeded():
    from faultline.ingest import brain_intents

    assert "runbook" in A.KINDS and "runbooks_about" in A.BRAIN_TOOLS
    assert "runbook" in {x["intent"] for x in brain_intents.exemplars()}


def test_month_and_year_dates_become_slot_words_for_the_graph_router():
    assert T.route_text("Who owned x in April 2026?") == "Who owned x in a past date?"
    assert T.route_text("Who owned x on March 3, 2026?") == "Who owned x on a past date?"
    assert T.route_text("Who owned x in 2026-02?") == "Who owned x in a past date?"
    assert T.route_text("Who may know x?") == "Who may know x?"


class _Session:
    def __init__(self, found: dict[str, dict] | None = None):
        self.found, self.calls, self.route = found or {}, [], {}

    def call(self, name, **args):
        self.calls.append((name, args))
        if name == "resolve_entity" and args.get("by_name"):
            return {"rows": [x for k, x in self.found.items() if k in args["text"].split() and "matched" in x]}
        if name == "resolve_entity":
            hit = self.found.get(args["text"]) if not args["fuzzy"] else None
            return {"rows": [hit] if hit else []}
        if name == "trace_decision":
            return {"rows": [{"id": args["decision_id"], "head": args["decision_id"], "status": "active"}]} \
                if args["decision_id"] in self.found else {"rows": []}
        return {"rows": []}


def test_a_two_letter_word_is_tried_only_as_an_exact_id():
    s = _Session({"ad": {"id": "ad", "label": "Service"}})
    assert A._entity(s, "Who owned ad last June?")["id"] == "ad"
    s = _Session()
    A._entity(s, "Who owned ad last June?")
    assert ("resolve_entity", {"text": "ad", "fuzzy": False}) in s.calls
    assert ("resolve_entity", {"text": "ad", "fuzzy": True}) not in s.calls
    assert not any(a["text"] in ("on", "it", "june", "last") for n, a in s.calls if n == "resolve_entity")


def test_a_decision_named_by_its_id_is_read_directly():
    s = _Session({"ADR-021": {}})
    A._baseline(s, "Who agreed on adr-21, and are they still here?")
    tried = [a["decision_id"] for n, a in s.calls if n == "trace_decision"]
    assert tried[:3] == ["adr-21", "ADR-21", "ADR-021"] and tried.count("ADR-021") >= 2   # found, then traced


@pytest.mark.parametrize("q,kind", [
    ("which revenue services don't have an owner or runbook", "gaps"),
    ("do all tier-1 revenue services have a playbook?", "gaps"),
    ("Which services does nobody own?", "gaps"),
    ("which runbooks are overdue for review", "knowledge"),
    ("are there decisions where everyone who decided them has left?", "knowledge"),
    ("what moved teams without getting a runbook", "knowledge"),
    ("who put the payment change freeze in place", "decision"),
    ("mid july 2026, which decisions and runbooks applied to product catalog?", "asof"),
    ("Who decided the retry rule in March 2026?", "decision"),          # "who decided" keeps its deciders
    ("anyone been working on the shopping basket lately", "people"),
    ("I need a change in the quote calculator. Which team owns it?", "people"),
    ("The exec revenue number jumped overnight. What steps do we follow?", "runbook"),
])
def test_keyword_kinds_cycle_two(q, kind):
    assert A._intent(q) == kind


def _named(i, matched, words=4):
    return {"id": i, "label": "Service", "name": i, "matched": matched, "words": words, "via": "name"}


def test_a_name_covering_more_of_the_question_beats_a_one_word_exact_id():
    s = _Session({"shipping": {"id": "shipping"}, "shipping quote calculator": {}})
    s.found["shipping"] = {"id": "shipping"}
    s.call = _with_names(s, [_named("quote", 3), _named("shipping", 2, 5)])
    assert A._entity(s, "Which team owns the shipping quote calculator?")["id"] == "quote"


def test_an_exact_id_wins_a_tie_and_a_clear_name_is_taken_without_one():
    s = _Session({"cart": {"id": "cart"}})
    s.call = _with_names(s, [_named("cache", 1), _named("cart", 1)])
    assert A._entity(s, "What breaks if cart fails?")["id"] == "cart"
    s = _Session()
    s.call = _with_names(s, [_named("cache", 1)])
    assert A._entity(s, "If valkey goes down, what breaks?")["id"] == "cache"
    s = _Session()
    s.call = _with_names(s, [_named("a", 1), _named("b", 1)])   # two equal one-word matches: not a clear name
    assert A._entity(s, "If thing goes down, what breaks?") is None


def _with_names(s, rows):
    plain = s.call

    def call(name, **args):
        if name == "resolve_entity" and args.get("by_name"):
            s.calls.append((name, args))
            return {"rows": rows}
        return plain(name, **args)
    return call


class _KnowSession:
    route: dict = {}

    def __init__(self):
        self.calls = []

    def call(self, name, **args):
        self.calls.append((name, args))
        if name == "knowledge_health":
            return {"rows": [{"kind": "stale_runbook", "id": "svc-a", "why": "runbook rb-a not reviewed for 99 days"},
                             {"kind": "missing_edge", "id": "svc-b", "why": "6 incidents"},
                             {"kind": "decision_deciders_left", "id": "ADR-1", "why": "everyone who decided it has left (p-001)"}]}
        return {"rows": []}


def test_knowledge_answers_lead_with_the_kind_asked_and_show_who_left():
    s = _KnowSession()
    s.route = {"stage": "keyword"}
    intent, text, _ = A._baseline(s, "Are any active decisions orphaned, with everyone who made them gone?")
    assert intent == "knowledge"
    first = text.splitlines()[1]
    assert first.startswith("- [ADR-1] decision nobody who made it is left") and "[p-001]" in first
    assert "the one you asked about first" in text and "[svc-a]" in text   # the rest still listed, after it
    intent, text, _ = A._baseline(s, "Where is our knowledge decaying?")   # nothing specific asked: every kind, as found
    assert text.splitlines()[1].startswith("- [svc-a]") and "[ADR-1]" in text and "[svc-b]" in text
