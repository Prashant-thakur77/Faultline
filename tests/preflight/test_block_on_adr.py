"""Live S6 (Mode B): a PR raising the payment client timeout and dropping retries is BLOCKED with the ADR links,
the path to the revenue entry and the owner team's reviewers; the same file inside the decision's bounds is not."""

import json

import pytest
from fastapi.testclient import TestClient

from faultline import api
from faultline.graph import client
from faultline.preflight.engine import PreflightIn, run

pytestmark = pytest.mark.live
REPO = "Prashant-thakur77/faultline-demo-app"
BEFORE = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}, "currency": "USD"}, indent=2)


def _pr(n, after, path="src/payment/config.json", before=BEFORE):
    return PreflightIn(repo=REPO, number=n, title="t", author="someone-else",
                       files=[{"path": path, "before": before, "after": after}])


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    client.engine().select_graph("tenant_acme").query(
        "MATCH (p:PR) WHERE p.number >= 9000 OPTIONAL MATCH (p)-[:ASSERTS]->(f:ChangeFact) DETACH DELETE f, p")


def test_s6_blocks_with_adr_and_reviewers():
    bad = json.dumps({"client": {"timeout_ms": 5000, "retries": 0}, "currency": "USD"}, indent=2)
    r = run("acme", _pr(9001, bad))
    assert r["verdict"] == "block"
    assert {d["id"] for d in r["decision_links"]} == {"ADR-012", "ADR-013"}
    assert "checkout" in r["assessment"]["revenue_tier1"] and r["reviewers"]
    assert any(w["term"] == "decision" for w in r["would_change_if"]) or r["risk"] - r["terms"]["decision"]["weighted"] >= 0.65


def test_within_bounds_is_not_blocked_and_not_a_contradiction():
    ok = json.dumps({"client": {"timeout_ms": 1800, "retries": 2}, "currency": "USD"}, indent=2)
    r = run("acme", _pr(9002, ok))
    assert r["verdict"] != "block" and r["terms"]["decision"]["value"] == 0.0


def test_low_blast_component_is_allowed_quietly():
    r = run("acme", _pr(9003, "x = 2\n", path="src/ad/main.java", before="x = 1\n"))
    assert r["verdict"] in ("allow", "require_review") and r["risk"] < 0.65


def test_api_returns_comment_on_block():
    api._rate.clear()
    bad = json.dumps({"client": {"timeout_ms": 9000, "retries": 2}}, indent=2)
    with TestClient(api.app) as c:
        res = c.post("/api/preflight", json=_pr(9004, bad).model_dump())
        assert res.status_code == 200
        body = res.json()
        assert body["verdict"] == "block" and "ADR-012" in body["comment"]
        assert c.post("/api/preflight", json={"repo": "bad repo", "number": 1, "files": []}).status_code == 422


def test_last_preflight_is_readable_by_pr_id():
    api._rate.clear()
    bad = json.dumps({"client": {"timeout_ms": 9000, "retries": 2}}, indent=2)
    with TestClient(api.app) as c:
        c.post("/api/preflight", json=_pr(9005, bad).model_dump())
        got = c.get("/api/preflight", params={"pr": f"pr:{REPO}#9005"})
        body = got.json()
        assert got.status_code == 200 and body["verdict"] == "block"
        assert body["evidence"]["params"] == {"pr": f"pr:{REPO}#9005"} and "ADR-012" in body["comment"]
        assert {f["key"] for f in body["facts"]} == {"payment.client.timeout_ms", "payment.currency"}  # currency removed
        assert c.get("/api/preflight", params={"pr": "pr:nope#1"}).status_code == 404


def test_a_code_constant_raising_the_timeout_is_blocked_like_the_config():
    """No model: the changed literal constant takes the decision's own rule key (Q-DEC-KEYS), so Q-DEC-1 sees it."""
    r = run("acme", _pr(9005, "export const CLIENT_TIMEOUT_MS = 5000;\n", path="src/payment/client.js",
                        before="export const CLIENT_TIMEOUT_MS = 1500;\n"))
    assert {"key": "payment.client.timeout_ms", "value": 5000, "about": "payment", "file": "file:src/payment/client.js"} \
        in r["facts"]
    assert r["verdict"] == "block" and "ADR-012" in {d["id"] for d in r["decision_links"]}
    ok = run("acme", _pr(9006, "export const CLIENT_TIMEOUT_MS = 1800;\n", path="src/payment/client.js",
                         before="export const CLIENT_TIMEOUT_MS = 1500;\n"))
    assert ok["terms"]["decision"]["value"] == 0.0                       # within the decision's bound
