"""Live: the retroactive preflight backtest (evals/backtest.py) and the as-of read path it uses.

- drift guard: at a far-future instant the as-of templates score every historical PR exactly like the live ones;
- no future: an as-of read never counts an incident opened at or after the merge, nor the PR's own incident;
- read-only: a full backtest leaves the golden graph unchanged;
- refactor: the S6 PR (on a fresh GRAPH.COPY) scores exactly as the pre-refactor formula and still blocks.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest

from faultline.graph import client
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO
from faultline.preflight import score as P

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
FAR = 10**15


def _bt():
    spec = importlib.util.spec_from_file_location("backtest", ROOT / "evals" / "backtest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def bt():
    return _bt()


def _ro(tenant):
    g = f"golden_{tenant}"
    if not gcopy.exists(client.engine(), g):
        pytest.skip(f"{g} not seeded")
    return RO(tenant, g)


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_as_of_far_future_scores_exactly_like_live(tenant, bt):
    ro = _ro(tenant)
    chk = {x["id"]: float(x["score"] or 0) for x in ro.run("Q-CHOKE-ALL", {}).rows}
    prs = bt.history(ro)
    assert prs
    for p in prs:
        live, asof = P.gather(ro, p["pr"], chokepoints=chk), P.gather(ro, p["pr"], as_of=FAR, chokepoints=chk)
        a, b = P.score(live), P.score(asof)
        assert (a.risk, a.verdict, a.terms) == (b.risk, b.verdict, b.terms), p["pr"]
        assert live.bus == asof.bus, p["pr"]


@pytest.mark.parametrize("tenant", ["acme", "globex"])
def test_as_of_never_sees_the_future(tenant, bt, db):
    ro = _ro(tenant)
    g = db.select_graph(f"golden_{tenant}")
    opened = {r[0]: r[1] for r in g.ro_query("MATCH (i:Incident) RETURN i.id, coalesce(i.opened_at, i.onset_at)").result_set}
    fewer = 0
    for p in bt.history(ro):
        rows = ro.run("Q-PRE-2-ASOF", {"pr": p["pr"], "as_of": p["merged_at"]}).rows
        seen = {i for r in rows for i in r["past_incidents"]}
        assert all(opened[i] < p["merged_at"] for i in seen), p["pr"]
        assert not seen & set(p["caused"]), f"{p['pr']} sees the incident it caused"
        now = {i for r in ro.run("Q-PRE-2", {"pr": p["pr"]}).rows for i in r["past_incidents"]}
        assert seen <= now
        fewer += len(seen) < len(now)
    assert fewer > 0  # the filter actually removes later incidents


def test_bus_factor_as_of_counts_only_earlier_commits(db):
    ro = _ro("acme")
    g = db.select_graph("golden_acme")
    comp, first, last = g.ro_query("MATCH (k:Commit) WITH k.component_id AS c, min(k.at) AS lo, max(k.at) AS hi, count(k) AS n "
                                   "WHERE n > 10 RETURN c, lo, hi ORDER BY n DESC LIMIT 1").result_set[0]
    mid = (first + last) // 2
    expect = g.ro_query("MATCH (k:Commit {component_id: $c}) WHERE k.at < $t RETURN count(k)", {"c": comp, "t": mid}).result_set[0][0]
    then = ro.run("Q-ORG-BUS-ASOF", {"target": comp, "as_of": mid}).rows[0]
    now = ro.run("Q-ORG-BUS", {"target": comp}).rows[0]
    assert then["total"] == expect < now["total"]
    assert ro.run("Q-ORG-BUS-ASOF", {"target": comp, "as_of": first}).rows == []  # nothing committed yet


def test_backtest_is_read_only_and_consistent(bt, db):
    _ro("acme")
    g = db.select_graph("golden_acme")
    count = "MATCH (n) OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n), count(r)"
    before = g.ro_query(count).result_set
    r = bt.run("acme")
    assert g.ro_query(count).result_set == before
    n_prs = g.ro_query("MATCH (p:PR) WHERE p.merged_at IS NOT NULL RETURN count(p)").result_set[0][0]
    assert r["graph"] == "golden_acme" and r["prs"] == n_prs and r["causing_prs"] > 0
    assert r["diagnostics"]["self_leaks"] == 0
    for v in r["variants"].values():
        for m in v.values():
            assert all(m[k] is None or 0.0 <= m[k] <= 1.0 for k in ("catch_rate", "block_rate", "flag_rate", "precision", "auroc"))
            c = m["confusion"]
            assert sum(c["causing"].values()) == m["causing"] and sum(c["other"].values()) == m["prs"] - m["causing"]
    json.dumps(r)  # serialisable into the results JSON


def test_s6_scores_exactly_as_before_the_refactor():
    from faultline.preflight.engine import PreflightIn, run

    spec = importlib.util.spec_from_file_location("test_score", ROOT / "tests" / "preflight" / "test_score.py")
    ts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ts)

    _ro("acme")
    db = client.engine()
    dst = f"eval_acme_backtest_s6_{uuid.uuid4().hex[:8]}"
    gcopy.copy_graph(db, "golden_acme", dst)
    try:
        before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}}, indent=2)
        bad = json.dumps({"client": {"timeout_ms": 5000, "retries": 0}}, indent=2)
        out = run("acme", PreflightIn(repo="eval/demo-app", number=9900, title="S6", author="eval",
                                      files=[{"path": "src/payment/config.json", "before": before, "after": bad}]), graph=dst)
        f = P.gather(RO("acme", dst), out["pr"])
        risk, verdict, _ = ts.LEGACY(f.impact.rows, f.comps, f.decisions, f.chokepoints, f.bus)
        assert (out["risk"], out["verdict"]) == (risk, verdict) == (P.score(f).risk, "block")
    finally:
        gcopy.delete_if_exists(db, dst)
