"""Unit tests (no FalkorDB) for the shared preflight scoring (`preflight/score.py`) and its as-of read path.

The refactor guard: `score()` must equal the formula `preflight_change` computed inline before the refactor (kept
below as LEGACY, verbatim apart from taking its inputs as arguments) on every shape of input, including the S6 PR.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from faultline.agent.rules import violated
from faultline.agent.weights import weights
from faultline.graph.templates import load
from faultline.preflight import score as P


def LEGACY(imp_rows, comps, dec, chk, bus):  # noqa: N802  (pre-refactor body of tools.preflight_change)
    w = weights()["preflight"]
    changed = sorted({c["changed"] for c in comps})
    top = max(chk.values(), default=0.0) or 1.0
    impacted = sorted({r["impacted"] for r in imp_rows} - set(changed))
    rev = [r["impacted"] for r in imp_rows if r["revenue"] and r["impacted"] not in changed]
    rev1 = sorted({r["impacted"] for r in imp_rows if r["revenue"] and r["tier"] == 1 and r["impacted"] not in changed})
    past = {c["changed"]: c["past_incidents"] for c in comps}
    gaps = [c["changed"] for c in comps if not c["team"] or not c["runbooks"]]
    terms = {
        "blast": (min(1.0, len(impacted) / 10), ""),
        "revenue": (1.0 if rev1 else (0.5 if rev else 0.0), ""),
        "betweenness": (max(chk.get(c, 0.0) / top for c in changed), ""),
        "past_incidents": (min(1.0, max(len(v) for v in past.values()) / 5), ""),
        "decision": (1.0 if any(d["violated"] for d in dec) else (0.5 if any(d["violated"] is None for d in dec) else 0.0), ""),
        "bus_factor": (1.0 if min(bus.values()) <= 1 else 0.0, ""),
        "uncertainty": (len(gaps) / len(changed), ""),
    }
    weight_key = {"blast": "w_blast", "revenue": "w_revenue", "betweenness": "w_betweenness", "past_incidents": "w_past_incidents",
                  "decision": "w_decision", "bus_factor": "w_bus_factor", "uncertainty": "w_uncertainty"}
    parts = {k: float(w[weight_key[k]]) * v for k, (v, _) in terms.items()}
    risk = round(sum(parts.values()), 4)

    def verdict_of(score: float, decision_violated: bool) -> str:
        v = "block" if score >= w["thresholds"]["block"] else ("require_review" if score >= w["thresholds"]["require_review"] else "allow")
        return "require_review" if v == "allow" and decision_violated else v

    violated_any = terms["decision"][0] == 1.0
    verdict = verdict_of(risk, violated_any)
    would = [k for k, part in sorted(parts.items(), key=lambda kv: -kv[1])
             if part > 0 and verdict_of(risk - part, violated_any and k != "decision") != verdict]
    return risk, verdict, would


def _imp(*rows):
    return SimpleNamespace(rows=[dict(zip(("changed", "impacted", "tier", "revenue"), r)) for r in rows], truncated=False)


def _comp(c, past=(), team=("team-x",), runbooks=("rb-1",), reviewers=()):
    return {"changed": c, "label": "Service", "past_incidents": list(past), "team": list(team), "runbooks": list(runbooks),
            "reviewers": list(reviewers)}


def _dec(op, actual, expected):
    d = {"decision": "D-1", "title": "t", "rule_key": "k", "op": op, "expected": expected, "actual": actual, "url": "u", "about": "a"}
    d["violated"] = violated(op, actual, expected)
    return d


# The S6 PR (payment config: timeout 1500 → 5000, retries 2 → 0) as the live graph answers it: reaches checkout (tier-1
# revenue) and more, payment is a chokepoint, ADR-012/013 are contradicted. Synthetic ids are fine: this is the shape.
S6 = P.Facts(pr="pr:x#1", impact=_imp(("svc-a", "svc-a", 1, False), *[("svc-a", f"svc-{i}", 1 + i % 2, i < 2) for i in range(8)]),
             comps=[_comp("svc-a", past=["i1", "i2", "i3"])], decisions=[_dec("<=", 5000, 2000), _dec(">=", 0, 1)],
             chokepoints={"svc-a": 20.0, "svc-z": 12.0}, bus={"svc-a": 2})

CASES = {
    "s6": S6,
    "quiet": P.Facts(pr="p", impact=_imp(("q", "q", 3, False)), comps=[_comp("q")], chokepoints={"q": 0.0}, bus={"q": 3}),
    "tier2_revenue_gap": P.Facts(pr="p", impact=_imp(("a", "a", 2, False), ("a", "b", 2, True)),
                                 comps=[_comp("a", team=()), _comp("c", runbooks=(), past=["i"] * 7)],
                                 chokepoints={"a": 3.0, "c": 1.0}, bus={"a": 1, "c": 4}),
    "undecidable_decision": P.Facts(pr="p", impact=_imp(*[("a", f"n{i}", 1, i == 3) for i in range(14)]),
                                    comps=[_comp("a")], decisions=[_dec("<=", "not-a-number", 3)], chokepoints={}, bus={"a": 0}),
    "violated_but_low_risk": P.Facts(pr="p", impact=_imp(("a", "a", 3, False)), comps=[_comp("a")],
                                     decisions=[_dec("<=", 9, 3)], chokepoints={"a": 0.0}, bus={"a": 5}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_score_equals_the_pre_refactor_formula(name):
    f = CASES[name]
    s = P.score(f)
    risk, verdict, would = LEGACY(f.impact.rows, f.comps, f.decisions, f.chokepoints, f.bus)
    assert (s.risk, s.verdict, [x["term"] for x in s.would]) == (risk, verdict, would)
    assert s.risk == round(sum(s.parts.values()), 4)


def test_s6_shape_blocks_and_violated_decision_is_never_allow():
    assert P.score(S6).verdict == "block"
    assert P.score(CASES["violated_but_low_risk"]).verdict == "require_review"


@pytest.mark.parametrize("term", P.TERMS)
def test_ablation_removes_exactly_one_weighted_term(term):
    full, ab = P.score(S6), P.score(S6, without=(term,))
    w = weights()["preflight"][f"w_{term}"]
    assert ab.parts[term] == 0.0 and ab.terms[term] == full.terms[term]
    assert ab.risk == pytest.approx(full.risk - w * full.terms[term][0], abs=1e-4)
    assert all(ab.parts[k] == full.parts[k] for k in P.TERMS if k != term)


def test_ablation_rejects_unknown_terms_and_empty_facts():
    with pytest.raises(ValueError):
        P.score(S6, without=("nope",))
    with pytest.raises(ValueError):
        P.score(P.Facts(pr="p", impact=_imp(), comps=[]))


def test_ablating_decision_also_drops_the_never_allow_rule():
    assert P.score(CASES["violated_but_low_risk"], without=("decision",)).verdict == "allow"


# ------------------------------------------------------------------ the as-of read path
class FakeRO:
    def __init__(self, comps=("svc-a",)):
        self.calls: list[tuple[str, dict]] = []
        self.comps = comps

    def run(self, tid, params):
        self.calls.append((tid, dict(params)))
        rows = {"Q-PRE-1": [], "Q-PRE-1-ASOF": [], "Q-PRE-2": [_comp(c) for c in self.comps], "Q-PRE-2-ASOF": [_comp(c) for c in self.comps],
                "Q-DEC-1": [], "Q-CHOKE-ALL": [{"id": "svc-a", "score": 2.0}],
                "Q-ORG-BUS": [{"bus_factor": 2}], "Q-ORG-BUS-ASOF": [{"bus_factor": 1}]}[tid]
        return SimpleNamespace(rows=rows, truncated=False)


def test_live_path_uses_the_live_templates():
    ro = FakeRO()
    f = P.gather(ro, "pr-1")
    assert [t for t, _ in ro.calls] == ["Q-PRE-1", "Q-PRE-2", "Q-DEC-1", "Q-CHOKE-ALL", "Q-ORG-BUS"]
    assert f.as_of is None and f.bus == {"svc-a": 2}


def test_as_of_path_uses_the_as_of_templates_with_the_instant():
    ro = FakeRO(comps=("svc-a", "svc-b"))
    f = P.gather(ro, "pr-1", as_of=1_700_000_000_000, chokepoints={"svc-a": 1.0})
    ids = [t for t, _ in ro.calls]
    assert ids == ["Q-PRE-1-ASOF", "Q-PRE-2-ASOF", "Q-DEC-1", "Q-ORG-BUS-ASOF", "Q-ORG-BUS-ASOF"]  # no Q-CHOKE-ALL: reused
    assert all(p["as_of"] == 1_700_000_000_000 for t, p in ro.calls if t.endswith("-ASOF"))
    assert f.chokepoints == {"svc-a": 1.0} and f.bus == {"svc-a": 1, "svc-b": 1}


def test_unmapped_pr_stops_after_two_reads():
    ro = FakeRO(comps=())
    f = P.gather(ro, "pr-1", as_of=5)
    assert not f.changed and [t for t, _ in ro.calls] == ["Q-PRE-1-ASOF", "Q-PRE-2-ASOF"]


def test_as_of_templates_filter_on_the_instant():
    t = load("Q-PRE-2-ASOF").display
    assert "coalesce(i.opened_at, i.onset_at) < $as_of" in t           # incidents known before the merge only
    assert "OWNED_AT" in t and "o.to > $as_of" in t                    # owner then, not now
    assert "r.valid_from, 0) <= $as_of" in t                           # runbooks valid then
    assert "coalesce(r.valid_from, 0) <= $as_of" in load("Q-PRE-1-ASOF").display  # the topology as it was (M14 #7)
    b = load("Q-ORG-BUS-ASOF").display
    assert "k.at < $as_of" in b and "MEMBER_OF" in b and "m.to > $as_of" in b
    h = load("Q-PRE-HIST")
    assert h.limit == 100 and "p.merged_at > $after" in h.display


def test_as_of_templates_return_the_columns_score_reads():
    for live, asof in (("Q-PRE-2", "Q-PRE-2-ASOF"), ("Q-ORG-BUS", "Q-ORG-BUS-ASOF")):
        cols = lambda tid: {c for c in ("changed", "past_incidents", "team", "runbooks", "bus_factor")  # noqa: E731
                            if f" AS {c}" in load(tid).display}
        assert cols(live) == cols(asof)


def test_backtest_variants_cover_only_known_terms():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("backtest", Path(__file__).resolve().parents[2] / "evals" / "backtest.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    assert set(itertools.chain(*bt.VARIANTS.values())) <= set(P.TERMS) and bt.VARIANTS["full"] == ()


def test_an_intentional_override_for_this_pr_is_not_a_violation_but_accidental_is():
    """M15 #3: the same rule as G8 (agent/rules.py::apply_override), applied when preflight gathers Q-DEC-1."""
    def ro_with(override):
        ro = FakeRO()
        base = ro.run

        def run(tid, params):
            r = base(tid, params)
            if tid == "Q-DEC-1":
                r.rows = [{"decision": "adr-1", "title": "t", "rule_key": "timeout_ms", "op": "<=", "expected": 2000,
                           "actual": 5000, "url": None, "about": "svc-a", "override": override}]
            return r
        ro.run = run
        return ro

    plain = P.gather(ro_with(None), "pr-1")
    waived = P.gather(ro_with({"verdict": "intentional", "by": "p-1", "why": "on purpose", "at": 1}), "pr-1")
    slip = P.gather(ro_with({"verdict": "accidental", "by": "p-1", "why": "oops", "at": 1}), "pr-1")
    assert plain.decisions[0]["violated"] is True and slip.decisions[0]["violated"] is True
    assert waived.decisions[0]["violated"] is False and waived.decisions[0]["overridden"] is True
    assert P.score(plain).terms["decision"][0] == 1.0 and P.score(waived).terms["decision"][0] == 0.0
