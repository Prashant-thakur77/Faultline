"""Live: the reversal guard (M17, Q-DEC-REV). A PR that puts back a value the org decided once and later reversed is
named in the preflight result and comment, with the decision in force and its evidence; it never changes the verdict
or the risk (the score, and so the backtest, are untouched). A PR that follows the decision in force says nothing."""

import uuid

import pytest

from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.preflight import score as P
from faultline.preflight.engine import PreflightIn, run
from faultline.graph.ro import RO

pytestmark = pytest.mark.live
BEFORE = "db:\n  migration_mode: online\n  pool: 20\n"


@pytest.fixture()
def dst():
    db = client.engine()
    name = f"eval_acme_reversal_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", name)
    try:
        yield name
    finally:
        gcopy.delete_if_exists(db, name)


def _pr(dst, n, after):
    return run("acme", PreflightIn(repo="eval/demo-app", number=n, title="catalog db config", author="eval",
                                   files=[{"path": "src/product-catalog/config.yaml", "before": BEFORE, "after": after}]), graph=dst)


def test_reinstating_a_reversed_decision_is_named_but_never_scored(dst):
    out = _pr(dst, 9901, BEFORE + "  migration_window: off_peak\n")
    (r,) = out["reversals"]
    assert r["reversed"] == "ADR-009" and r["head"] == "ADR-021"
    assert r["because"] and not any(c["id"].startswith("doc-adr-") for c in r["because"])
    from faultline.preflight.comment import render

    assert "Reinstates a reversed decision" in (render(out) or "")   # rendered as the API renders it
    f = P.gather(RO("acme", dst), out["pr"])
    assert (out["risk"], out["verdict"]) == (P.score(f).risk, P.score(f).verdict)   # the score never reads Q-DEC-REV


def test_following_the_decision_in_force_raises_nothing(dst):
    out = _pr(dst, 9902, BEFORE.replace("pool: 20", "pool: 30"))
    assert out["reversals"] == []


def test_brain_answer_subgraph_connects_cited_ids_through_the_domain_graph():
    from fastapi.testclient import TestClient

    from faultline import api

    c = TestClient(api.app)
    r = c.get("/api/brain/subgraph", params={"ids": "ADR-012,payment,p-004", "tenant": "acme"})
    assert r.status_code == 200
    d = r.json()
    rels = {(e["source"], e["rel"], e["target"]) for e in d["edges"]}
    assert ("ADR-012", "CONSTRAINS", "payment") in rels and ("p-004", "DECIDED", "ADR-012") in rels
    assert {n["id"] for n in d["nodes"] if n["cited"]} == {"ADR-012", "payment", "p-004"}
    assert not any(n["label"] in ("ToolCall", "Evidence", "Run") for n in d["nodes"])   # never through run records
    assert c.get("/api/brain/subgraph", params={"ids": "x'; DROP", "tenant": "acme"}).status_code == 422
