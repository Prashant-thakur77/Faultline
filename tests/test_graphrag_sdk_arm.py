"""Unit (no engine, no SDK, no API): the GraphRAG-SDK comparison grades what its pre-registration says, and its spend
guard can never let a call through past the cap.

* grading: written ids (case- and separator-insensitive), exact names and titles → ids, fabricated ids, the
  abstention phrases, the FL rule (brain_heldout) and the SDK rule, strict unanswerable;
* summary: per-arm counts, paired outcomes, McNemar;
* worker Meter: a call whose worst case would pass the cap is refused unsent; real usage is added after a call.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import graphrag_sdk_arm as A  # noqa: E402
import graphrag_sdk_worker as W  # noqa: E402
import report  # noqa: E402

ROWS = [  # id, labels, name, title (the shape IdIndex reads from golden_acme)
    ["fraud-detection", ["Node", "Service"], "fraud detection consumer", None],
    ["product-catalog", ["Node", "Service"], "product catalog", None],
    ["cart", ["Node", "Service"], "cart shopping basket", None],
    ["cache", ["Node", "Datastore"], "valkey cart cache", None],
    ["team-platform", ["Node", "Team"], "Platform", None],
    ["team-payments", ["Node", "Team"], "Payments", None],
    ["p-006", ["Node", "Person"], "Florin Ashcombe", None],
    ["ADR-021", ["Node", "Decision"], None, "Catalog DB schema changes use online migrations"],
    ["rb-recs-cache", ["Node", "Runbook"], None, "Recommendation cache stampede"],
    ["recommendation", ["Node", "Service"], "product recommendation", None],
    ["inc-h006", ["Node", "Incident"], None, "Order event consumers fall behind"],
    ["raw.raw_orders", ["Node", "Table"], "raw orders", None],
]


@pytest.fixture(scope="module")
def idx():
    return A.IdIndex(rows=ROWS)


def test_written_ids_are_case_and_separator_insensitive(idx):
    t = "Fraud Detection moved to team platform; product_catalog and ADR 021 too; not cartography."
    assert idx.verbatim(t) == {"fraud-detection", "team-platform", "product-catalog", "ADR-021"}


def test_names_and_titles_map_to_ids_and_are_reported(idx):
    cited, names = A.text_cited("Florin Ashcombe wrote 'Catalog DB schema changes use online migrations'; the Payments "
                                "team and the valkey cart cache.", idx)
    assert {"p-006", "ADR-021", "team-payments", "cache"} <= cited
    assert names["florin-ashcombe"] == ["p-006"] and names["payments"] == ["team-payments"]


def test_incident_titles_are_not_names(idx):
    assert A.text_cited("Order event consumers fall behind", idx)[0] == set()


def test_fabricated_ids_are_id_shaped_tokens_not_in_the_graph(idx):
    assert A.fabricated("see ADR-021, ADR-099 and p-777; inc-h006 is real", idx) == ["ADR-099", "p-777"]


@pytest.mark.parametrize("text,abstains", [
    ("There is no information about a loyalty points service.", True),
    ("The context does not mention a CDN vendor budget.", True),
    ("No decision about the cache TTL is recorded.", True),
    ("I could not find that.", True),
    ("Team Platform owns it.", False),
    ("Checkout does not wait for the email.", False),
])
def test_abstention_phrases(text, abstains):
    assert bool(A.ABSTAIN.search(text)) is abstains


def test_grade_rules(idx):
    q = {"expect": ["team-platform"]}
    assert A.grade(q, "x", {"team-platform"}, False, idx, "fl")["ok"] is False      # FL needs its guard
    assert A.grade(q, "x", {"team-platform"}, True, idx, "fl")["ok"] is True
    assert A.grade(q, "Platform owns it", {"team-platform"}, True, idx, "sdk")["ok"] is True
    una = {"expect": []}
    assert A.grade(una, "I could not find it", set(), True, idx, "fl")["ok"] is True
    assert A.grade(una, "I could not find it", {"cart"}, True, idx, "fl")["ok"] is False
    g = A.grade(una, "No decision on the recommendation cache TTL is recorded.", {"recommendation"}, True, idx, "sdk")
    assert g["ok"] is True and g["ok_strict"] is False
    assert A.grade(una, "The Platform team owns loyalty points.", {"team-platform"}, True, idx, "sdk")["ok"] is False


def test_summarise_counts_and_pairs(idx, monkeypatch):
    qs = [{"set": "s2", "id": "B01", "q": "who owns fraud detection", "expect": ["team-platform"]},
          {"set": "s2", "id": "B02", "q": "who owns loyalty", "expect": []}]
    fl = [{"set": "s2", "id": "B01", "answer": "[team-platform]", "citations": ["team-platform"], "guard_ok": True,
           "intent": "owner", "ms": 10.0},
          {"set": "s2", "id": "B02", "answer": "I could not find it.", "citations": [], "guard_ok": True,
           "intent": "owner", "ms": 5.0}]
    sdk = {"answers": [{"set": "s2", "id": "B01", "answer": "The Payments team.", "ms": 900.0, "usd": 0.01, "in": 9000,
                        "out": 100},
                       {"set": "s2", "id": "B02", "answer": "There is no information about that.", "ms": 800.0,
                        "usd": 0.012, "in": 9500, "out": 80}]}
    monkeypatch.setitem(A.SETS, "s2", "heldout_blind2.truth.json")
    out = A.summarise(qs, fl, sdk, idx)["sets"]["s2"]
    assert out["fl"]["correct"] == 2 and out["sdk"]["correct"] == 1
    assert out["sdk"]["unanswerable_honest"] == 1 and out["sdk"]["usd"] == 0.022
    assert out["paired"] == {"both": 1, "fl_only": 1, "sdk_only": 0, "neither": 0, "mcnemar_p": 1.0}


def test_mcnemar_and_wilson():
    assert A.mcnemar_exact(0, 0) == 1.0
    assert A.mcnemar_exact(5, 0) == 0.0625
    assert A.wilson(0, 0) is None
    lo, hi = A.wilson(24, 40)
    assert lo < 0.6 < hi


class _Resp:
    def __init__(self, tin: int, tout: int) -> None:
        self.usage = type("U", (), {"prompt_tokens": tin, "completion_tokens": tout})()
        self.choices = [type("C", (), {"finish_reason": "stop"})()]


def test_meter_refuses_unsent_and_records_real_usage():
    sent = []

    async def acompletion(**kw):
        sent.append(kw)
        return _Resp(1000, 200)

    fake = type("L", (), {"acompletion": staticmethod(acompletion), "completion": staticmethod(lambda **kw: None)})
    m = W.Meter(cap=0.05)
    m.wrap(fake)
    msg = [{"role": "user", "content": "x" * 250}]   # worst case: 100 tokens in + 8,192 out = US$0.0411
    asyncio.run(fake.acompletion(model="m", messages=msg))
    assert len(sent) == 1 and m.spent == pytest.approx(1000e-6 + 200 * 5e-6) and m.reserved == 0
    m.spent = 0.02   # now the worst case would pass the cap: refused, never sent
    with pytest.raises(W.BudgetRefused):
        asyncio.run(fake.acompletion(model="m", messages=msg))
    assert len(sent) == 1 and m.refused == 1


def test_report_fold_keys_and_section(idx, monkeypatch):
    qs = [{"set": "s2", "id": "B01", "q": "who owns fraud detection", "expect": ["team-platform"]},
          {"set": "s2", "id": "B02", "q": "who owns loyalty", "expect": []}]
    fl = [{"set": "s2", "id": "B01", "answer": "[team-platform]", "citations": ["team-platform"], "guard_ok": True,
           "intent": "owner", "ms": 10.0},
          {"set": "s2", "id": "B02", "answer": "I could not find it.", "citations": [], "guard_ok": True,
           "intent": "owner", "ms": 5.0}]
    sdk = {"answers": [{"set": "s2", "id": "B01", "answer": "Team Platform.", "ms": 900.0, "usd": 0.01, "in": 9000,
                        "out": 100},
                       {"set": "s2", "id": "B02", "answer": "There is no information.", "ms": 800.0, "usd": 0.012,
                        "in": 9500, "out": 80}]}
    monkeypatch.setitem(A.SETS, "s2", "heldout_blind2.truth.json")
    x = {"config": {"model": "anthropic/claude-haiku-4-5", "sdk_version": "1.4.0", "cap_usd": 1.5},
         "corpus": {"docs": [{}] * 20, "documents": 13, "facts_docs": 7, "words": 8371}, "chunks": 52,
         "ingest": {"seconds": 100.0, "s_per_doc": 5.0, "cost": {"usd": 0.6, "in": 1, "out": 2, "calls": 52},
                    "doc_errors": []},
         "kg": {"labels": {"__Entity__": 300, "Chunk": 52}, "relationships": {"RELATES": 400}},
         "meter": {"spent_usd": 0.622, "refused": 0, "truncated": 0, "calls": 56}, "stopped": None,
         "skipped_sets": [{"set": "orig", "projection_usd": 1.9}], "step_failures": 1,
         "graphs_deleted": {"graphrag_acme": True, "graphrag_acme__ontology": True},
         **A.summarise(qs, fl, sdk, idx)}
    k = report.graphrag_keys(x)
    assert k["graphrag.s2.fl.correct"] == 2 and k["graphrag.s2.sdk.correct"] == 2 and k["graphrag.clean"] is True
    assert k["graphrag.s2.sdk.correct.n"] == 2 and k["graphrag.orig.skipped_projection_usd"] == 1.9
    assert k["graphrag.kg.entities"] == 300 and k["graphrag.corpus.chunks"] == 52
    md = "\n".join(report.graphrag_markdown(k))
    assert "GraphRAG-SDK" in md and "| correct of 2" in md
    assert report.graphrag_keys({}) == {} and report.graphrag_markdown({}) == []
    x["stopped"] = "budget"
    assert report.graphrag_keys(x)["graphrag.clean"] is False


def test_meter_retries_transport_errors_once_billed(monkeypatch):
    class RateLimitError(Exception):
        status_code = 429

    calls = {"n": 0}

    async def acompletion(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("rate limited")
        return _Resp(100, 10)

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(W.asyncio, "sleep", no_sleep)
    fake = type("L", (), {"acompletion": staticmethod(acompletion), "completion": staticmethod(lambda **kw: None)})
    m = W.Meter(cap=1.0)
    m.wrap(fake)
    asyncio.run(fake.acompletion(model="m", messages=[{"role": "user", "content": "hi"}]))
    assert calls["n"] == 3 and m.retries == 2 and len(m.calls) == 1 and m.reserved == 0

    async def bad(**kw):
        raise ValueError("not a transport error")

    fake2 = type("L", (), {"acompletion": staticmethod(bad), "completion": staticmethod(lambda **kw: None)})
    m2 = W.Meter(cap=1.0)
    m2.wrap(fake2)
    with pytest.raises(ValueError):
        asyncio.run(fake2.acompletion(model="m", messages=[]))
    assert m2.retries == 0 and m2.reserved == 0
