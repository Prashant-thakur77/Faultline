"""Live: the company brain reads what the documents SAY (T3). Document bodies are chunks with vecf32 embeddings;
search_knowledge (Q-KNOW-1) fuses seven index lists by reciprocal rank inside FalkorDB, credits a document's text to
the decision or runbook it produced, and expands to what each source concerns. The brain falls back to it only when
two independent indexes agree on the best source."""

from __future__ import annotations

import pytest

from faultline.brain.ask import ask
from faultline.graph import udf
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def acme(db):
    udf.load_udfs(db.connection)
    tok = context.bind("acme")
    yield db.select_graph("tenant_acme")
    context.unbind(tok)


def test_every_doc_has_chunks_with_vectors(acme):
    docs, chunked, vecs = acme.ro_query(
        "MATCH (d:Doc) WITH count(d) AS docs "
        "MATCH (c:Chunk)-[:PART_OF]->(d:Doc) RETURN docs, count(DISTINCT d), count(c.embedding)").result_set[0]
    assert docs == chunked and vecs > docs                          # every document is chunked, each chunk embedded


def test_the_passage_that_answers_wins(acme):
    r = T.search_knowledge(text="what happens when the confirmation email provider is down")
    assert r["template"] == "Q-KNOW-1"
    top = r["rows"][0]
    assert top["id"] == "ADR-004" and top["label"] == "Decision"      # the ADR's TEXT, credited to its decision
    assert set(top["via"]) == {"fulltext", "vector"} and "best-effort" in top["snippet"].lower()
    assert "checkout" in top["related"] and "p-019" in top["related"]  # what it constrains, who decided it
    scores = [x["score"] for x in r["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_superseded_and_current_decisions_come_together(acme):
    ids = [x["id"] for x in T.search_knowledge(text="who decided catalog migrations run at night")["rows"][:4]]
    assert {"ADR-009", "ADR-021"} <= set(ids)


def test_off_topic_text_finds_nothing(acme):
    assert T.search_knowledge(text="what is the capital of France")["rows"] == []


def test_the_brain_answers_from_documents_only_when_both_indexes_agree(acme):
    a = ask("why do charges get retried", "acme")
    assert a.intent == "documents" and a.guard["ok"] and "ADR-013" in a.citations
    assert "found by both words and meaning" in a.answer
    for q in ("what is the capital of France", "please restart payment now"):
        b = ask(q, "acme")
        assert b.intent == "none" and not b.citations                 # still an honest refusal
