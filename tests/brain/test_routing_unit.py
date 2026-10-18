"""Unit (no FalkorDB): the brain's two-stage question router.

* stage 1, the keyword router, decides whenever one of its patterns matches (no graph call); stage 2, a read-only
  query, decides only when none matches, and similarity is never computed in Python. `Answer.route.stage` says which;
* route_question runs Q-BRAIN-INTENT (vector + full-text over IntentExemplar nodes, fused in the engine) with the
  weights.yaml numbers as parameters, and routes on the engine's first row only: a row below the similarity floor or
  of a refusal kind routes nowhere;
* without the embedding model it says so and routes by full-text only (Q-BRAIN-INTENT-FT), never silently;
* the answerer refuses a question the graph stage cannot route ("I can't answer that from the graph") without calling anything else,
  and a broken router is reported as unavailable, never as a refusal;
* entity resolution never fuzzy- or full-text-matches the words the question kinds are asked with;
* the templates are linted and use the FalkorDB indexes; the seeded exemplars cover exactly the composer's kinds.
"""

from __future__ import annotations

import pytest

from faultline.agent.weights import weights
from faultline.brain import ask as A
from faultline.graph.ro import QueryResult
from faultline.graph.templates import load
from faultline.ingest import brain_intents
from faultline.mcp_server import context
from faultline.mcp_server import tools as T


def _row(intent, vsim, *, answerable=True, refuse=False, fts=10.0, ft_rel=1.0):
    return {"intent": intent, "vsim": vsim, "fts": fts, "ft_rel": ft_rel, "score": vsim + 0.05 * ft_rel,
            "refuse": refuse, "nearest": "ix-x", "nearest_text": "example", "answerable": answerable}


class _FakeRO:
    def __init__(self, rows: list[dict], vocab: list[str] | None = None):
        self.rows, self.vocab, self.calls = rows, vocab or [], []

    def run(self, tid: str, params: dict) -> QueryResult:
        self.calls.append((tid, params))
        rows = [{"word": w, "n": 1} for w in self.vocab] if tid == "Q-BRAIN-VOCAB" else self.rows
        return QueryResult(template_id=tid, cypher=load(tid).display, params=params, header=[], rows=rows, ms=0.1,
                           digest=f"d-{tid}", seen_ids=set(), served_by="test")


@pytest.fixture()
def bound():
    tok = context.bind("acme", record=False)
    yield
    context.unbind(tok)


@pytest.fixture()
def no_model(monkeypatch):
    import faultline.memory.embed as E

    monkeypatch.setattr(E, "embed", lambda texts: [[0.0] * E.DIM for _ in texts])


def test_slot_values_become_slot_words_and_nothing_else_changes():
    assert T.route_text("Who owned x on 2026-03-01?") == "Who owned x on a past date?"
    assert T.route_text("Who owned x during inc-h123?") == "Who owned x during an incident?"
    assert T.route_text("Who owned x during gx-inc-007, really") == "Who owned x during an incident, really"
    assert T.route_text("What breaks if  cart   fails?") == "What breaks if cart fails?"


def test_route_runs_the_fused_template_with_weights_from_code(monkeypatch, bound, no_model):
    ro = _FakeRO([_row("blast", 0.83), _row("obligations", 0.78)], vocab=["breaks", "if", "what"])
    monkeypatch.setattr(T, "_ro", lambda: ro)
    out = T.route_question(text="What breaks if cart fails?")
    w = weights()["brain"]
    tid, p = ro.calls[0]
    assert tid == "Q-BRAIN-INTENT" and p["k"] == w["route_k"] and p["w_ft"] == w["route_ft_weight"]
    assert p["min_sim"] == w["route_min_similarity"] and len(p["q"]) == 384 and p["text"] == "what | breaks | if | cart | fails"
    assert out["routed"] == "blast" and out["mode"] == "vector+fulltext" and "note" not in out
    assert out["question_words"] == ["breaks", "if", "what"]
    assert out["evidence_id"].startswith("ev_") and "Q-BRAIN-INTENT" in out["template"] and "Q-BRAIN-VOCAB" in out["template"]
    assert "db.idx.vector.queryNodes" in out["cypher"] and "db.idx.fulltext.queryNodes" in out["cypher"]


@pytest.mark.parametrize("top", [_row("people", 0.55, answerable=False),                     # below the floor
                                 _row("out_of_scope", 0.9, answerable=False, refuse=True)])  # a refusal kind
def test_an_unanswerable_first_row_routes_nowhere_even_if_a_later_row_is_answerable(monkeypatch, bound, no_model, top):
    monkeypatch.setattr(T, "_ro", lambda: _FakeRO([top, _row("context", 0.62)]))
    assert T.route_question(text="What is the stock price of a fruit company?")["routed"] is None


def test_without_the_model_it_routes_by_full_text_only_and_says_so(monkeypatch, bound):
    import faultline.memory.embed as E

    def boom(texts):
        raise ImportError("fastembed missing")

    monkeypatch.setattr(E, "embed", boom)
    ro = _FakeRO([{**_row("decision", 0.0, fts=12.0), "vsim": None, "ft_rel": None, "score": 12.0}])
    monkeypatch.setattr(T, "_ro", lambda: ro)
    out = T.route_question(text="What did we decide about retries?")
    assert ro.calls[0][0] == "Q-BRAIN-INTENT-FT" and ro.calls[0][1]["min_ft"] == weights()["brain"]["route_ft_min"]
    assert out["mode"] == "fulltext" and "full-text only" in out["note"] and out["routed"] == "decision"


def test_route_validates_its_input(bound):
    assert T.route_question(text="??")["error"].startswith("invalid arguments")
    assert "no words" in T.route_question(text="?? !!")["error"]
    assert T.route_question(text="x" * 501)["error"].startswith("invalid arguments")


def test_route_fails_loudly_when_the_graph_is_disabled(monkeypatch, bound, no_model):
    from faultline.config import settings

    monkeypatch.setattr(settings, "faultline_disable_graph", True)   # ablation arm A4 still works: a loud error
    out = T.route_question(text="What breaks if cart fails?")
    assert "disabled" in out["error"] and "rows" not in out


class _FakeSession:
    """Records the brain's tool calls; answers route_question with a canned engine ranking."""

    def __init__(self, route: dict):
        self.route_out, self.calls, self.route = route, [], {}

    def call(self, name, **args):
        self.calls.append((name, args))
        if name == A.ROUTE_TOOL:
            return self.route_out
        return {"rows": []}


def _routed(rows, routed, mode="vector+fulltext", words=()):
    return {"rows": rows, "routed": routed, "mode": mode, "question_words": list(words), "evidence_id": "ev_x"}


def test_a_weak_match_is_refused_after_one_document_search_finds_nothing():
    s = _FakeSession(_routed([_row("people", 0.55, answerable=False), _row("history", 0.5, answerable=False)], None))
    intent, text, _ = A._baseline(s, "What is the stock price of a fruit company?")
    assert intent == "none" and text.startswith(A.REFUSAL)
    assert "people" in text and "0.55" in text and f"{weights()['brain']['route_min_similarity']:.2f}" in text
    # no entity resolution and no answer template: only the documents are searched (one read-only query) first
    assert [c[0] for c in s.calls] == [A.ROUTE_TOOL, "search_knowledge"]
    assert s.route["stage"] == "graph" and s.route["routed"] is None
    assert not A._cited(text)                                   # a refusal cites nothing


def test_a_refusal_kind_is_refused_as_out_of_scope():
    s = _FakeSession(_routed([_row("out_of_scope", 0.8, answerable=False, refuse=True)], None))
    intent, text, _ = A._baseline(s, "Restart the pods please")
    assert intent == "none" and text.startswith(A.REFUSAL) and "not a question about" in text
    assert [c[0] for c in s.calls] == [A.ROUTE_TOOL]          # a request to act is never searched for


class _DocSession(_FakeSession):
    def __init__(self, route: dict, docs: list[dict]):
        super().__init__(route)
        self.docs = docs

    def call(self, name, **args):
        if name == "search_knowledge":
            self.calls.append((name, args))
            return {"rows": self.docs}
        return super().call(name, **args)


def _doc(i, via, related=()):
    return {"id": i, "title": f"title of {i}", "snippet": f"what {i} says", "via": list(via), "related": list(related)}


def test_documents_answer_only_when_words_and_meaning_agree_on_the_best_source():
    weak = _routed([_row("people", 0.55, answerable=False)], None)
    s = _DocSession(weak, [_doc("ADR-1", ("fulltext", "vector"), ("svc-a",)), _doc("ADR-2", ("vector",))])
    intent, text, _ = A._baseline(s, "why do we do it this way")
    assert intent == "documents" and "[ADR-1]" in text and "[svc-a]" in text and "[ADR-2]" not in text
    s = _DocSession(weak, [_doc("ADR-2", ("vector",)), _doc("ADR-1", ("fulltext", "vector"))])
    intent, text, _ = A._baseline(s, "why do we do it this way")
    assert intent == "none" and text.startswith(A.REFUSAL) and not A._cited(text)


def test_a_router_error_is_unavailable_not_a_refusal():
    s = _FakeSession({"error": "unavailable: graph disabled (FAULTLINE_DISABLE_GRAPH=true)"})
    intent, text, _ = A._baseline(s, "If cart crashes, what else fails?")   # no keyword: the graph stage routes it
    assert "routing is unavailable" in text and "disabled" in text and not text.startswith(A.REFUSAL)


def test_a_question_no_keyword_matches_is_routed_by_the_graph():
    q = "Which services make money but are unattended?"
    assert A._intent(q) is None
    s = _FakeSession(_routed([_row("gaps", 0.95)], "gaps"))
    intent, _, _ = A._baseline(s, q)
    assert intent == "gaps" and [c[0] for c in s.calls] == [A.ROUTE_TOOL, "missing_guardrails"]
    assert s.route["stage"] == "graph" and s.route["routed"] == "gaps" and s.route["evidence_id"]


@pytest.mark.parametrize("q,kind,matched", [
    ("Which services have no owner?", "gaps", "no owner"),
    ("What breaks if cart fails?", "blast", "breaks"),
    ("Who was the owner of ad on 2026-06-01?", "owner_then", "owner + a time"),
    ("Who is the owner on call for checkout?", "people", "Who"),
])
def test_a_keyword_match_decides_without_calling_the_graph_router(q, kind, matched):
    s = _FakeSession(_routed([_row("context", 0.99)], "context"))   # the graph would say otherwise; it is never asked
    intent, _, _ = A._baseline(s, q)
    assert intent == kind and A.ROUTE_TOOL not in [c[0] for c in s.calls]
    assert s.route == {"stage": "keyword", "routed": kind, "matched": matched}


def test_only_the_graph_stage_refuses():
    """A keyword-routed question is never refused by the similarity floor; refusal is the fallback's alone."""
    s = _FakeSession(_routed([_row("people", 0.1, answerable=False)], None))
    intent, text, _ = A._baseline(s, "What is the impact of a rename?")
    assert intent == "blast" and not text.startswith(A.REFUSAL)


def test_keyword_kinds_are_composer_kinds():
    assert {name for name, _ in A.INTENTS} <= set(A.KINDS)


def test_a_kind_the_composer_does_not_handle_is_refused_loudly():
    s = _FakeSession(_routed([_row("horoscope", 0.95)], "horoscope"))
    intent, text, _ = A._baseline(s, "What is my horoscope?")
    assert intent == "none" and "does not handle" in text


def test_entity_resolution_never_fuzzy_or_fulltext_matches_question_words():
    s = _FakeSession(_routed([], None))
    s.route = {"question_words": ["feature", "flags"]}
    assert A._entity(s, "Show the feature flags gizmo") is None
    fuzzy = [a["text"] for n, a in s.calls if n == "resolve_entity" and a["fuzzy"]]
    exact = [a["text"] for n, a in s.calls if n == "resolve_entity" and not a["fuzzy"]]
    found = [a["text"] for n, a in s.calls if n == "find_entities"]
    assert "feature" in exact                                    # every word is still tried as an exact id
    assert "feature" not in fuzzy and fuzzy == ["gizmo"] and found == ["gizmo"]


@pytest.mark.parametrize("tid,index", [("Q-BRAIN-INTENT", "db.idx.vector.queryNodes"),
                                       ("Q-BRAIN-INTENT", "db.idx.fulltext.queryNodes"),
                                       ("Q-BRAIN-INTENT-FT", "db.idx.fulltext.queryNodes"),
                                       ("Q-BRAIN-VOCAB", "db.idx.fulltext.queryNodes")])
def test_routing_templates_are_linted_and_use_the_engine_indexes(tid, index):
    t = load(tid)   # load() lints: literal LIMIT, ORDER BY, CALL allowlist, no writes
    assert index in t.display and "IntentExemplar" in t.display and not t.seen   # exemplar ids are never citable


def test_seeded_exemplars_cover_exactly_the_composers_kinds():
    xs = brain_intents.exemplars()
    answerable = {x["intent"] for x in xs if not x["refuse"]}
    assert answerable == set(A.KINDS)
    assert {x["intent"] for x in xs if x["refuse"]} == {"out_of_scope"}
    assert len({x["id"] for x in xs}) == len(xs) and all(x["id"].startswith("ix-") for x in xs)
    b = brain_intents.build()   # committed vectors match the YAML texts (else it raises: regenerate)
    rows = b.nodes["IntentExemplar"]
    assert len(rows) == len(xs) and all(len(r["embedding"]) == 384 for r in rows)


def test_exemplars_are_tenant_agnostic():
    """No exemplar names a component, team or person of any tenant: they say "this service", never an id."""
    import re

    import yaml

    from faultline.config import REPO_ROOT

    ids: set[str] = set()
    for path in (REPO_ROOT / "data" / "topology").glob("*.yaml"):
        doc = yaml.safe_load(path.read_text()) or {}
        for key in ("services", "datastores"):
            ids |= {str(x["id"]).lower() for x in (doc.get(key) or []) if isinstance(x, dict) and x.get("id")}
    assert ids, "no topology ids found to check against"
    for x in brain_intents.exemplars():
        words = set(re.findall(r"[a-z0-9][a-z0-9-]*", x["text"].lower()))
        assert not words & ids, (x["text"], words & ids)
