"""docs: ADR + runbook corpus → Decision/Runbook/Doc rows (no FalkorDB)."""

from __future__ import annotations

import hashlib
import json

import pytest

from faultline.graph.schema_model import NODE_LABELS, REL_TYPES
from faultline.ingest import docs, history

B = docs.build()
NODES = {lbl: {r["id"]: r for r in rows} for lbl, rows in B.nodes.items()}


def _rows(rel, src=None, dst=None):
    return [r for (t, s, d), rows in B.edges.items()
            if t == rel and src in (None, s) and dst in (None, d) for r in rows]


def _canon(b) -> str:
    return json.dumps({"n": {k: v for k, v in sorted(b.nodes.items())},
                       "e": {"|".join(k): v for k, v in sorted(b.edges.items())}}, sort_keys=True)


def test_deterministic():
    assert _canon(docs.build()) == _canon(B)


def test_whitelisted_and_tenant_scoped():
    assert set(B.nodes) <= NODE_LABELS
    for rel, src, dst in B.edges:
        assert rel in REL_TYPES and src in NODE_LABELS and dst in NODE_LABELS
    assert all(r["tenant"] == "acme" for rows in B.nodes.values() for r in rows)


def test_corpus_shape():
    assert sorted(NODES["Decision"]) == ["ADR-004", "ADR-009", "ADR-012", "ADR-013", "ADR-021"]
    assert sorted(NODES["Runbook"]) == ["rb-catalog-lock", "rb-checkout-degraded", "rb-kafka-lag",
                                        "rb-payment-errors", "rb-recs-cache"]
    assert len(NODES["Doc"]) == 13  # 5 ADRs + 5 runbooks + 2 chats + 1 issue
    assert sorted(d["id"] for d in NODES["Doc"].values() if d.get("kind") in ("chat", "issue")) == [
        "doc-chat-catalog-migrations", "doc-chat-payment-timeouts", "doc-issue-checkout-payment-isolation"]
    assert {d["kind"] for d in NODES["Doc"].values()} == {"adr", "runbook", "chat", "issue"}


def test_adr009_superseded_by_adr021():
    assert NODES["Decision"]["ADR-009"]["status"] == "superseded"
    assert NODES["Decision"]["ADR-021"]["status"] == "active"
    assert [(r["src"], r["dst"]) for r in _rows("SUPERSEDES")] == [("ADR-021", "ADR-009")]
    assert {d["status"] for k, d in NODES["Decision"].items() if k != "ADR-009"} == {"active"}


def test_rule_fields_typed():
    d = NODES["Decision"]
    assert (d["ADR-012"]["rule_key"], d["ADR-012"]["rule_op"]) == ("payment.client.timeout_ms", "<=")
    assert d["ADR-012"]["rule_value"] == 2000 and type(d["ADR-012"]["rule_value"]) is int
    assert (d["ADR-013"]["rule_key"], d["ADR-013"]["rule_op"], d["ADR-013"]["rule_value"]) == (
        "payment.client.retries", ">=", 2)
    assert type(d["ADR-013"]["rule_value"]) is int
    assert (d["ADR-004"]["rule_key"], d["ADR-004"]["rule_op"]) == ("checkout.email.blocking", "==")
    assert d["ADR-004"]["rule_value"] is False
    for x in d.values():
        assert isinstance(x["decided_at"], int) and x["url"].startswith("data/gen/docs/")


def test_constraints_point_at_topology():
    cons = {(r["src"], r["dst"]) for r in _rows("CONSTRAINS")}
    assert {("ADR-004", "checkout"), ("ADR-012", "payment"), ("ADR-013", "payment")} <= cons
    assert ("ADR-021", "astronomy-db") in {(r["src"], r["dst"]) for r in _rows("CONSTRAINS", "Decision", "Datastore")}


def test_provenance_edges():
    produced = {r["dst"]: r["src"] for r in _rows("PRODUCED")}
    assert set(produced) == set(NODES["Decision"]) | set(NODES["Runbook"])
    cites = {(r["src"], r["dst"]) for r in _rows("CITES")}
    for did, doc in produced.items():
        if did in NODES["Decision"]:
            assert (did, doc) in cites
    assert ("ADR-021", "doc-adr-009") in cites


def test_digests_stable_and_match_files():
    again = {d["id"]: d["digest"] for d in docs.build().nodes["Doc"]}
    for d in NODES["Doc"].values():
        assert again[d["id"]] == d["digest"]
        raw = (docs.DOCS_DIR / d["url"].removeprefix("data/gen/docs/")).read_bytes()
        assert d["digest"] == hashlib.sha256(raw).hexdigest()


def test_runbooks_target_services_and_history_symptoms():
    symptoms = {s["id"] for s in history.build().nodes["Symptom"]}
    for r in _rows("RUNBOOK_FOR", "Runbook", "Symptom"):
        assert r["dst"] in symptoms
    assert {r["src"] for r in _rows("RUNBOOK_FOR", "Runbook", "Service")} == set(NODES["Runbook"])
    for rb in NODES["Runbook"].values():
        assert rb["source"] == "human" and rb["body"] and rb["salience"] == 1.0
        assert isinstance(rb["valid_from"], int) and isinstance(rb["reviewed_at"], int)


@pytest.mark.parametrize("front, err", [
    ("id: ADR-1\nkind: adr\ntitle: t\nstatus: active\ndecided_at: 2026-01-01\nreviewed_at: 2026-01-01\n"
     "rule_key: k\nrule_op: '<'\nrule_value: 1\n", "rule_op"),
    ("id: ADR-1\nkind: adr\ntitle: t\nstatus: active\ndecided_at: 2026-01-01\nreviewed_at: 2026-01-01\n"
     "rule_key: k\nrule_op: '<='\nrule_value: lots\n", "numeric"),
    ("id: ADR-1\nkind: adr\ntitle: t\nstatus: superseded\ndecided_at: 2026-01-01\nreviewed_at: 2026-01-01\n"
     "rule_key: k\nrule_op: '=='\nrule_value: x\n", "no superseding"),
    ("id: rb-x\nkind: runbook\ntitle: t\nsource: robot\nreviewed_at: 2026-01-01\nservices: [payment]\n", "source"),
])
def test_contract_violations_fail_loudly(tmp_path, front, err):
    (tmp_path / "x.md").write_text(f"---\n{front}---\nbody\n")
    with pytest.raises(docs.DocError, match=err):
        docs.build(docs_dir=tmp_path)
