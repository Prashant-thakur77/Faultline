"""Unit: the LLM arm on the deep/decisive benches (evals/llm_deep.py), its report keys, the shared A0 outcome mapping
(evals/llm_arms.py) and the simulator's paged topology read (sim/telemetry.sim_view). No API call, no FalkorDB."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "backend"))

import llm_arms  # noqa: E402
import llm_deep  # noqa: E402
import report  # noqa: E402


@pytest.mark.parametrize("bench", llm_deep.BENCHES)
def test_generated_titles_carry_no_hint(bench):
    cases = llm_deep.cases_for(bench)
    assert len(cases) == {"deep": 140, "decisive": 40}[bench]
    assert all(llm_deep.title_problems(c) == [] for c in cases)


def test_title_check_catches_a_hint():
    bad = {"spec": {"inject": [{"change": "D-0123abcd", "target": "cart", "title": "cart: revert the bad deploy"}],
                    "report": "cart errors are elevated", "name": "generated incident c1"}}
    probs = llm_deep.title_problems(bad)
    assert any("neutral template" in p for p in probs) and any("revert" in p for p in probs)
    leaky_id = {"spec": {"inject": [{"change": "D-cause", "target": "cart", "title": "cart: change"}], "report": "", "name": ""}}
    assert any("opaque" in p for p in llm_deep.title_problems(leaky_id))


def test_outcome_mapping_is_v2():
    assert llm_arms.outcome_of({"cause": "D-1", "incident": True}) == ("CONFIRMED", "D-1", None)
    assert llm_arms.outcome_of({"cause": "none", "incident": True, "origin": "ad"}) == ("NOT_CONFIDENT", None, "ad")
    assert llm_arms.outcome_of({"cause": "none", "incident": False}) == ("NO_INCIDENT", None, None)
    assert llm_arms.outcome_of({"cause": None}) == ("NO_INCIDENT", None, None)


def _case(cat, cause, changes=("D-aaaaaaaa", "D-bbbbbbbb")):
    exp = ({"outcome": "CONFIRMED", "cause": cause, "eliminated": {}} if cause else
           {"outcome": "NOT_CONFIDENT", "cause": None, "eliminated": {}})
    return {"id": "x", "category": cat, "expected": exp,
            "spec": {"inject": [{"change": c, "target": "t", "title": "t: change"} for c in changes]}}


def test_grading_follows_the_bench_rules():
    c = _case("deep_onpath", "D-aaaaaaaa")
    g = llm_deep.grade(c, "deep", "CONFIRMED", "D-aaaaaaaa")
    assert g["right_cause"] and not g["wrong_confident"] and g["ok"]
    g = llm_deep.grade(c, "deep", "CONFIRMED", "D-bbbbbbbb")
    assert g["wrong_confident"] and not g["right_cause"] and not g["ok"]
    g = llm_deep.grade(c, "deep", "CONFIRMED", "D-nothere")   # a made-up id is a wrong named change
    assert g["wrong_confident"] and g["named_unknown"]
    g = llm_deep.grade(c, "deep", "NOT_CONFIDENT", None)        # abstaining on a deep_onpath world is not ok
    assert g["abstained"] and not g["ok"]
    g = llm_deep.grade(_case("weak_link", "D-aaaaaaaa"), "deep", "NOT_CONFIDENT", None)   # ABSTAIN_FINE
    assert g["abstained"] and g["ok"]
    nc = _case("abstain_downstream", None)
    g = llm_deep.grade(nc, "deep", "CONFIRMED", "D-aaaaaaaa")   # any blame where nothing should be blamed
    assert g["wrong_confident"] and not g["has_cause"]
    g = llm_deep.grade(nc, "deep", "NO_INCIDENT", None)         # neither an abstention nor a blame
    assert g["no_incident"] and not g["abstained"] and not g["wrong_confident"] and not g["ok"]
    g = llm_deep.grade(c, "decisive", "UNPARSED", None)
    assert g["unparsed"] and not (g["right_cause"] or g["wrong_confident"] or g["abstained"]) and "ok" not in g


def test_price_is_the_list_price():
    assert llm_arms.PRICE_PER_MTOK == {"in": 4.0, "out": 20.0}
    assert llm_deep.usd(1_000_000, 1_000_000) == 24.0
    tin, tout = llm_deep.est_tokens("x" * 1600)
    assert tin == 1001 and tout == llm_deep.OUT_TOKENS_EST


def test_paid_run_refuses_over_budget_before_any_call(tmp_path, monkeypatch):
    from faultline.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-used")
    monkeypatch.setattr(llm_deep, "render", lambda c: pytest.fail("rendered past the budget check"))
    monkeypatch.setattr(llm_arms, "_ask", lambda *a: pytest.fail("called the API past the budget check"))
    out = tmp_path / "llm_deep.json"
    cases = [_case("deep_onpath", "D-aaaaaaaa") | {"id": f"db{i:03d}"} for i in range(3)]
    assert llm_deep.paid_run("deep", cases, approved=0.0001, reason="t", resume=False, out=out) == 3
    assert not out.exists()


def test_report_keys_and_section(monkeypatch):
    rows = {f"db{i:03d}": {"id": f"db{i:03d}", "category": "abstain_downstream" if i < 2 else "deep_onpath",
                           **llm_deep.grade(_case("abstain_downstream" if i < 2 else "deep_onpath",
                                                  None if i < 2 else "D-aaaaaaaa"), "deep",
                                            "CONFIRMED", "D-aaaaaaaa"),
                           "usage": {"input_tokens": 2000 + i, "output_tokens": 200}, "seconds": 3.0,
                           "matches_dry_run": True} for i in range(4)}
    side = {"llm_deep.json": {"model": "claude-opus-5-5", "prompt_version": 2,
                              "benches": {"deep": {"worlds": rows, "complete": False, "runs": [{"spent_usd": 0.05}]}}},
            "llm_deep_dryrun.json": {"deep": {"n": 140, "est_usd": 5.54, "est_input_tokens": 334560}}}
    monkeypatch.setattr(report, "_side", lambda name: side.get(name, {}))
    k = report.llm_deep_keys()
    assert k["llm_deep.deep.all.cases"] == 4 and k["llm_deep.deep.all.cause_cases"] == 2
    assert k["llm_deep.deep.all.right_cause"] == 2 and k["llm_deep.deep.all.wrong_confident"] == 2
    assert k["llm_deep.deep.all.right_cause.n"] == 2 and k["llm_deep.deep.all.wrong_confident.n"] == 4
    assert k["llm_deep.deep.abstain_downstream.wrong_confident"] == 2
    assert k["llm_deep.deep.tokens_in_median"] == 2001.5 and k["llm_deep.deep.cost_usd"] == 0.05
    assert k["llm_deep_dry.deep.est_usd"] == 5.54
    md = "\n".join(report.new_benches_markdown(k))
    assert "| LLM alone | 2/2" in md and "partial" in md and "| abstain_downstream | 2 | n/a | 2 |" in md


class _Res:
    def __init__(self, rows, truncated):
        self.rows, self.truncated = rows, truncated


class _PagedRO:
    """Q-SIM-2 over a fake edge list, 100 rows a page (keyset on (src, dst)), as the template does."""

    def __init__(self, edges):
        self.edges = sorted(edges)
        self.calls = []

    def run(self, tid, params):
        assert tid == "Q-SIM-2"
        self.calls.append(params)
        after = (params["after_src"], params["after_dst"])
        rest = [e for e in self.edges if (e[0], e[1]) > after]
        page = [{"src": u, "dst": v, "cap": 1.0, "rps": 1, "in_rps": 1} for u, v in rest[:100]]
        return _Res(page, len(rest) > 100)


def test_sim_view_pages_until_complete():
    from faultline.sim.telemetry import sim_view

    edges = [(f"s{i:03d}", f"c{j}") for i in range(61) for j in range(5)]   # 305 edges, like globex
    ro = _PagedRO(edges)
    view = sim_view(ro)
    assert [(r["src"], r["dst"]) for r in view] == sorted(edges)
    assert len(ro.calls) == 4 and ro.calls[0] == {"after_src": "", "after_dst": ""}


def test_sim_view_refuses_a_repeated_pair():
    from faultline.sim.telemetry import sim_view

    class Dup(_PagedRO):
        def run(self, tid, params):
            return _Res([{"src": "a", "dst": "b", "cap": 1.0, "rps": 1, "in_rps": 1}] * 2, False)

    with pytest.raises(RuntimeError, match="twice"):
        sim_view(Dup([]))


def test_dry_run_file_if_present_is_consistent():
    p = ROOT / "evals" / "results" / "llm_deep_dryrun.json"
    if not p.exists():
        pytest.skip("no dry run recorded")
    d = json.loads(p.read_text())
    for bench, r in d.items():
        assert r["n"] == len(r["worlds"]) and r["model"] == llm_deep.MODEL
        assert r["est_input_tokens"] == sum(w["est_in"] for w in r["worlds"].values())
        assert r["est_usd"] == round(llm_deep.usd(r["est_input_tokens"], r["est_output_tokens"]), 2)
