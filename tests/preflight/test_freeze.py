"""M20 #6: change-freeze windows decided in FalkorDB from the wall clock (Q-PRE-FREEZE).

The seeded policy POL-freeze-payment-weekend (data/gen/policies/acme.yaml): no payment changes from Friday 16:00 to
Monday 09:00 IST (UTC+05:30). FalkorDB turns the instant into local time with
`localdatetime('1970-01-01T00:00:00') + duration({seconds: …})` and tests the ISO weekday / hour / minute against the
window, which wraps the week. A freeze in force tightens the preflight verdict with the policy cited; it is never a score
term (risk and backtest unchanged). Unit tests need no engine; the rest are live on tenant_acme or a clean room.
"""

import datetime as dt
import json
import uuid

import pytest

from faultline.preflight import comment
from faultline.preflight import score as P

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
POLICY = "POL-freeze-payment-weekend"


def ms(y, mo, d, h, mi=0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=IST).timestamp() * 1000)


# 2026-10-16 is a Friday, 2026-10-18 a Sunday, 2026-10-19 a Monday, 2026-10-15 a Thursday (local dates, IST)
CASES = [
    ("friday 17:05", ms(2026, 10, 16, 17, 5), True),
    ("friday 16:00", ms(2026, 10, 16, 16, 0), True),
    ("friday 15:59", ms(2026, 10, 16, 15, 59), False),
    ("saturday noon", ms(2026, 10, 17, 12), True),
    ("sunday noon", ms(2026, 10, 18, 12), True),        # 6.0.2's dayOfWeek says 0 for Sunday: read as 7
    ("monday 08:59", ms(2026, 10, 19, 8, 59), True),
    ("monday 09:00", ms(2026, 10, 19, 9, 0), False),
    ("thursday 17:05", ms(2026, 10, 15, 17, 5), False),
]


def test_a_freeze_only_tightens_the_verdict():
    block = [{"effect": "block"}]
    review = [{"effect": "require_review"}]
    assert P.apply_freeze("allow", block) == "block" and P.apply_freeze("require_review", block) == "block"
    assert P.apply_freeze("allow", review) == "require_review" and P.apply_freeze("block", review) == "block"
    assert P.apply_freeze("allow", []) == "allow"


def test_comment_cites_the_policy_and_the_engine_local_time():
    row = {"component": "payment", "policy": POLICY, "title": "No payment changes", "effect": "block", "day": 5,
           "hour": 17, "minute": 5, "utc_offset_min": 330, "decided_by": "p-004", "url": "data/gen/policies/acme.yaml"}
    md = comment.render({"pr": "pr:x#1", "verdict": "block", "risk": 0.4, "freeze": {"rows": [row]},
                         "evidence": {"evidence_id": "ev", "template": "Q-PRE-1"}})
    assert f"Change freeze {POLICY}" in md and "Friday 17:05 local (UTC+05:30)" in md and "p-004" in md


@pytest.mark.live
@pytest.mark.parametrize("name,at,held", CASES, ids=[c[0] for c in CASES])
def test_window_is_decided_in_the_engine(db, name, at, held):
    from faultline.graph.ro import RO

    r = P.freezes(RO("acme"), ["payment", "checkout"], at=at)
    assert [(x["component"], x["policy"]) for x in r.rows] == ([("payment", POLICY)] if held else []), name
    if held:
        x = r.rows[0]
        local = dt.datetime.fromtimestamp(at / 1000, IST)
        assert (x["day"], x["hour"], x["minute"]) == (local.isoweekday(), local.hour, local.minute)
        assert x["effect"] == "block" and x["decided_by"] == "p-004" and x["at"] == at


@pytest.mark.live
def test_engine_clock_is_the_default(db, monkeypatch):
    """The product passes no instant: FalkorDB's own clock (timestamp()) decides, and agrees with the wall clock."""
    from faultline.graph.ro import RO

    monkeypatch.setattr(P, "FREEZE_AT", None)
    r = P.freezes(RO("acme"), ["payment"])
    now = dt.datetime.now(IST)
    wm = (now.isoweekday() - 1) * 1440 + now.hour * 60 + now.minute
    expect = wm >= (5 - 1) * 1440 + 16 * 60 or wm < 9 * 60
    if abs(wm - 9 * 60) > 1 and abs(wm - (4 * 1440 + 16 * 60)) > 1:   # not within a minute of a boundary
        assert bool(r.rows) == expect
    assert r.params["at"] is None


@pytest.mark.live
def test_preflight_holds_a_payment_pr_inside_the_freeze_only(db, monkeypatch):
    """The whole Mode B path on a clean room: inside the window the verdict is block with the policy cited and the
    same risk; outside it the verdict is the score's; a retired policy holds nothing."""
    from faultline.graph import client
    from faultline.graph import copy as gcopy
    from faultline.preflight.engine import PreflightIn, run

    room = f"eval_acme_freeze_{uuid.uuid4().hex[:8]}"
    db_ = client.engine()
    ok = json.dumps({"client": {"timeout_ms": 1800, "retries": 2}, "currency": "USD"}, indent=2)
    before = json.dumps({"client": {"timeout_ms": 1500, "retries": 2}, "currency": "USD"}, indent=2)
    pr = PreflightIn(repo="Prashant-thakur77/faultline-demo-app", number=9301, title="tune payment timeout",
                     author="someone-else", files=[{"path": "src/payment/config.json", "before": before, "after": ok}])
    try:
        gcopy.copy_graph(db_, "tenant_acme", room)
        monkeypatch.setattr(P, "FREEZE_AT", ms(2026, 10, 14, 12))          # Wednesday: no freeze
        out = run("acme", pr, graph=room)
        assert out["verdict"] != "block" and out["freeze"]["rows"] == []
        monkeypatch.setattr(P, "FREEZE_AT", ms(2026, 10, 16, 17, 5))       # Friday 17:05 IST: frozen
        held = run("acme", pr, graph=room)
        assert held["verdict"] == "block" and held["score_verdict"] == out["verdict"] and held["risk"] == out["risk"]
        assert [r["policy"] for r in held["freeze"]["rows"]] == [POLICY]
        assert held["freeze"]["template"] == "Q-PRE-FREEZE" and "dayOfWeek" in held["freeze"]["cypher"]
        assert any(w["term"] == "freeze" for w in held["would_change_if"])
        assert f"Change freeze {POLICY}" in comment.render(held)
        db_.select_graph(room).query("MATCH (p:Policy {id: $id}) SET p.status = 'retired'", {"id": POLICY})
        assert run("acme", pr, graph=room)["verdict"] == out["verdict"]          # a retired policy holds nothing
    finally:
        gcopy.delete_if_exists(db_, room)
