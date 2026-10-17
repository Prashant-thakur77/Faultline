"""M21 learning, unit level (no engine): how learned preferences blend into the plan order (only within one
predicted-future class, never adding, removing or enabling an option), guideline flags, contract suggestions, the why
lines, learned responders in the first wave, who_fixes blending and knowledge-gap classification."""

from faultline.actions import act, contracts, oncall
from faultline.agent.weights import weights
from faultline.memory import learning

NOW = 1_800_000_000_000
FLAG_ARGS = {"repo": "o/r", "path": "flags.json", "flag": "someFlag", "state": "off", "reviewers": []}
RB_ARGS = {"repo": "o/r", "path": "deploys.json", "service": "svc", "revert": "chg-1", "reviewers": []}


def _opts():
    return [
        {"kind": "rollback_deploy", "option": "roll back chg-1", "target": "chg-1", "enabled": True, "reason": "removes it",
         "args": RB_ARGS, "future": {"predicted": "contains"}},
        {"kind": "flip_flag", "option": "flag someFlag → off", "target": "someFlag", "enabled": True, "reason": "cuts it",
         "args": FLAG_ARGS, "future": {"predicted": "contains"}},
        {"kind": "open_issue", "option": "open an issue", "target": "chg-1", "enabled": True, "reason": "tracks",
         "args": {"repo": "o/r"}, "future": {"predicted": "does_not_contain"}},
        {"kind": "flip_flag", "option": "cut a → b", "target": "b", "enabled": False, "reason": "no lever", "args": {}},
    ]


REMEDY = {"rows": [{"kind": "rollback_deploy", "target": "*", "successes": 6, "failures": 0, "n": 6, "rate": 0.875},
                   {"kind": "flip_flag", "target": "someFlag", "successes": 4, "failures": 1, "n": 5, "rate": 0.714}],
          "basis": "past incidents sharing a symptom"}


def _pref(kind, a, r, o, na, nr, tna, tn, last=NOW - 3_600_000):
    return {"id": f"pref|svc|{kind}", "family": "svc", "action_kind": kind, "approvals": a, "rejections": r, "others": o,
            "pref": (a + 1) / (a + r + o + 2), "n_approve": na, "n_reject": nr, "n_family_approve": tna, "n_family": tn,
            "last_at": last, "events": [f"le-{kind}-{i}" for i in range(na + nr)]}


def _learned(prefs, guidelines=(), suggestions=()):
    return {"rows": list(prefs), "guidelines": list(guidelines), "suggestions": list(suggestions), "family": "svc",
            "now": NOW, "n_family": max([p["n_family"] for p in prefs] or [0]), "evidence_id": "ev_x"}


def _kinds(opts):
    return [o["kind"] for o in opts]


def test_no_learning_keeps_the_existing_order_exactly():
    base = act.order_by_history(_opts(), REMEDY)
    same = act.order_by_history(_opts(), REMEDY, learned=None)
    assert [o["option"] for o in base] == [o["option"] for o in same]
    assert _kinds(base)[:2] == ["rollback_deploy", "flip_flag"]   # history: rollback 0.875 > flag 0.714


def test_five_flag_approvals_put_the_flag_first_with_a_why_line():
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([_pref("flip_flag", 5.0, 0.0, 0.0, 5, 0, 5, 5)]))
    assert _kinds(out)[:2] == ["flip_flag", "rollback_deploy"]
    flag = out[0]
    assert flag["learned"]["rank_without_learning"] == 2 and flag["learned"]["preference"]["n_approve"] == 5
    assert "your team approved the flag flip 5 of the last 5 time(s) for svc" in flag["reason"]
    assert "last 1 h ago" in flag["learned"]["preference"]["line"]
    # a permutation: same options, same enabled flags; the disabled option stays where it was
    assert sorted(o["option"] for o in out) == sorted(o["option"] for o in _opts())
    assert [o["enabled"] for o in out] == [o["enabled"] for o in act.order_by_history(_opts(), REMEDY)]
    assert out[3]["option"] == "cut a → b" and out[2]["kind"] == "open_issue"


def test_below_pref_min_n_choices_do_not_reorder():
    n = int(weights()["learn"]["pref_min_n"]) - 1
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([_pref("flip_flag", float(n), 0, 0, n, 0, n, n)]))
    assert _kinds(out)[:2] == ["rollback_deploy", "flip_flag"]
    assert "preference" not in out[1]["learned"] and out[1]["learned"]["rank_without_learning"] == 2


def test_learning_never_lifts_an_option_across_a_predicted_future_class():
    opts = _opts()
    opts[1]["future"] = {"predicted": "does_not_contain"}    # the flag is predicted NOT to contain
    out = act.order_by_history(opts, REMEDY, learned=_learned([_pref("flip_flag", 50.0, 0, 0, 50, 0, 50, 50)]))
    assert _kinds(out)[:2] == ["rollback_deploy", "flip_flag"]   # however strong the habit


def test_rejections_push_a_kind_down():
    # history alone puts the flag first here; the team rejected it three times and approved the rollback
    remedy = {"rows": [{"kind": "flip_flag", "target": "someFlag", "successes": 5, "failures": 0, "n": 5, "rate": 0.86},
                       {"kind": "rollback_deploy", "target": "*", "successes": 1, "failures": 1, "n": 2, "rate": 0.5}]}
    assert _kinds(act.order_by_history(_opts(), remedy))[:2] == ["flip_flag", "rollback_deploy"]
    learned = _learned([_pref("flip_flag", 0.0, 3.0, 1.0, 0, 3, 1, 4), _pref("rollback_deploy", 1.0, 0, 0, 1, 0, 1, 4)])
    assert _kinds(act.order_by_history(_opts(), remedy, learned=learned))[:2] == ["rollback_deploy", "flip_flag"]


def test_an_active_guideline_flags_the_option_and_moves_it_after_its_class_a_proposed_one_only_annotates():
    gd = {"id": "gl-abc123", "text": "never flip it at peak", "family": "svc", "action_kind": "rollback_deploy",
          "status": "proposed", "by": "p-1", "by_name": "Ann", "at": NOW - 60_000, "incident": "inc-1", "event": "le-1"}
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([], [gd]))
    rb = next(o for o in out if o["kind"] == "rollback_deploy")
    assert out[0]["kind"] == "rollback_deploy" and rb["learned"]["guideline"]["needs_override"] is False
    assert "proposed guideline gl-abc123" in rb["reason"]
    active = {**gd, "status": "active", "decided_by": "p-2", "decided_by_name": "Bo"}
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([], [active]))
    rb = next(o for o in out if o["kind"] == "rollback_deploy")
    assert _kinds(out)[:2] == ["flip_flag", "rollback_deploy"] and rb["enabled"] is True   # never disabled
    assert rb["learned"]["guideline"]["needs_override"] and "explicit override" in rb["reason"]
    assert rb["learned"]["guideline"]["decided_by"] == "p-2" and rb["learned"]["guideline"]["decided_by_name"] == "Bo"


def test_contract_suggestion_only_for_the_exact_fix_and_never_when_covered():
    ph = contracts.params_hash("flip_flag", contracts.action_params("flip_flag", FLAG_ARGS))
    s = {"action_kind": "flip_flag", "params_hash": ph, "n": 2, "incidents": ["i1", "i2"], "events": ["e1", "e2"],
         "people": ["p-1"], "covered": False}
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([], suggestions=[s]))
    flag = next(o for o in out if o["option"].startswith("flag"))
    assert flag["learned"]["contract_suggestion"]["n"] == 2 and "standing approval" in flag["reason"]
    assert all("contract_suggestion" not in (o.get("learned") or {}) for o in out if o is not flag)
    other = {**s, "params_hash": "0" * 64}
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([], suggestions=[other]))
    assert all("contract_suggestion" not in (o.get("learned") or {}) for o in out)
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([], suggestions=[{**s, "covered": True}]))
    assert all("contract_suggestion" not in (o.get("learned") or {}) for o in out)


def test_plan_summary_reports_moves_and_learning_errors():
    out = act.order_by_history(_opts(), REMEDY, learned=_learned([_pref("flip_flag", 5.0, 0, 0, 5, 0, 5, 5)]))
    out = [{**o, "id": f"act-i-{k}"} for k, o in enumerate(out, 1)]
    s = learning.plan_summary(out, _learned([_pref("flip_flag", 5.0, 0, 0, 5, 0, 5, 5)]))
    assert s["applied"] and s["moved"] and s["family"] == "svc"
    assert learning.plan_summary(out, {"error": "unavailable: x"})["applied"] is False
    assert learning.plan_summary(out, None)["note"].startswith("learning not consulted")
    # the remedy summary still describes history alone (rollback first by history: not moved by history)
    assert act.remedy_summary(REMEDY, out)["moved"] is False


def test_first_wave_needs_resp_min_n_and_adds_at_most_resp_first_wave():
    k = int(weights()["learn"]["resp_min_n"])
    resp = {"target": "svc", "now": NOW, "evidence_id": "ev_r", "rows": [
        {"person": "p-9", "name": "Nine", "score": 3.0, "n": k + 1, "acks": k + 1, "approvals": 0, "fixes": 0,
         "mtta_ms": 60_000.0, "last_at": NOW - 120_000, "incidents": k + 1},
        {"person": "p-8", "name": "Eight", "score": 2.5, "n": k + 1, "acks": k + 1, "approvals": 0, "fixes": 0,
         "mtta_ms": None, "last_at": NOW, "incidents": k},
        {"person": "p-7", "name": "Seven", "score": 9.0, "n": k - 1, "acks": 1, "approvals": 0, "fixes": 0,
         "mtta_ms": None, "last_at": NOW, "incidents": 1}]}
    wave = learning.first_wave(resp)
    assert [p["person"] for p in wave] == ["p-9"][: int(weights()["learn"]["resp_first_wave"])]
    assert "learned responder for svc" in wave[0]["reason"] and "mean ack 60 s" in wave[0]["reason"]
    assert learning.first_wave({"error": "x"}) == [] and learning.first_wave(None) == []
    # recipients: the learned responder first, the rota and the blast-radius on-call still paged
    who = {"oncall_now": ["p-1"], "owner_team": "team-a", "evidence_id": "ev_w"}
    notify = {"rows": [{"team": "team-b", "name": "B", "owns_impacted": ["x"], "oncall": ["p-2"]}], "evidence_id": "ev_n"}
    people = oncall.recipients(who, notify, "svc", learned=wave)
    assert [p["person"] for p in people] == ["p-9", "p-1", "p-2"] and people[0]["learned"]
    assert [p["person"] for p in oncall.recipients(who, notify, "svc")] == ["p-1", "p-2"]


def test_blend_who_mixes_harmonic_and_responses():
    who = [{"person": "p-1", "name": "One", "score": 10.0}, {"person": "p-2", "name": "Two", "score": 8.0}]
    resp = {"rows": [{"person": "p-2", "name": "Two", "score": 4.0}, {"person": "p-5", "name": "Five", "score": 2.0}]}
    out = learning.blend_who(who, resp)
    assert [x["person"] for x in out] == ["p-2", "p-1", "p-5"]
    assert out[0]["harmonic"] == 8.0 and out[2]["harmonic"] is None
    assert [x["person"] for x in learning.blend_who(who, None)] == ["p-1", "p-2"]


def test_gap_reasons_come_from_the_answerers_own_words():
    assert learning.gap_reason("none", "I can't answer that from the graph: it does not match").startswith("refused")
    assert learning.gap_reason("none", "I can't answer that from the graph: it is not a question about the "
                                       "organisation's components, people, decisions or knowledge (small talk).") is None
    assert learning.gap_reason("decision", "No decision about that is documented in the graph.").startswith("unanswered")
    assert learning.gap_reason("owner", "I could not find that component in the graph (no id or name match).")
    assert learning.gap_reason("owner", "[payment] is owned by [team-payments] now.") is None
    assert learning.normalise("Who owns  the Payment-API?") == "who owns the payment-api"


def test_trust_rule_keys_and_bot_are_trusted_without_reading_the_graph():
    assert learning.trusted("acme", "eval_acme_x", "inc-1", key=True)[0]
    assert learning.trusted("acme", "eval_acme_x", "inc-1", via="telegram")[0]


def test_ago_and_event_ids():
    assert learning.ago(30_000) == "just now" and learning.ago(5 * 60_000) == "5 min ago"
    assert learning.ago(3 * 3_600_000) == "3 h ago" and learning.ago(2 * 86_400_000) == "2 days ago"
    assert learning.event_id("approve", "g", "i", "a") == learning.event_id("approve", "g", "i", "a")
    assert learning.event_id("approve", "g", "i", "a") != learning.event_id("reject", "g", "i", "a")


def test_learn_weights_are_documented():
    w = weights()["learn"]
    for k in ("half_life_days", "w_pref", "pref_min_n", "resp_min_n", "resp_first_wave", "contract_suggest_k"):
        assert k in w
    assert 0 <= float(w["w_pref"]) <= 1 and 0 <= float(weights()["memory"]["recall_recency_w"]) <= 1
