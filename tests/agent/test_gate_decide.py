"""Gate verdict arithmetic (pure): G7 correlation is downgrade-only, G8 is attached and never blocks."""

from faultline.agent.gate import Check, correlate, decide


def _hard(ok=True):
    return [Check(n, ok, "") for n in ("G1 grounded", "G2 path", "G3 time", "G4 quantitative", "G5 sufficiency",
                                       "G6 competitors")]


def _row(role, status="complete", named=(), via=()):
    return {"role": role, "status": status, "task": f"t-{role}", "named": list(named), "via": list(via)}


def test_g8_contradiction_is_attached_but_never_blocks_or_downgrades():
    checks = _hard() + [Check("G7 agreement", True, "", downgrade_only=True),
                        Check("G8 contradiction", False, "violates ADR-1", downgrade_only=True)]
    assert decide(checks) == (True, True)


def test_failing_g7_correlation_downgrades_without_rejecting():
    checks = _hard() + [Check("G7 agreement", True, "", downgrade_only=True),
                        Check("G7 correlation", False, "disagree", downgrade_only=True)]
    assert decide(checks) == (True, False)


def test_not_evaluable_never_counts_as_a_pass_for_hard_checks_and_does_not_downgrade():
    assert decide(_hard()[:-1] + [Check("G6 competitors", None, "")]) == (False, False)
    checks = _hard() + [Check("G7 agreement", True, "", downgrade_only=True),
                        Check("G7 correlation", None, "not evaluable", downgrade_only=True)]
    assert decide(checks) == (True, True)
    assert decide(_hard() + [Check("G7 agreement", False, "", downgrade_only=True)]) == (True, False)


def test_correlation_agrees_when_change_and_code_name_the_cause_via_changed():
    ok, detail = correlate("dep-1", [_row("change", named=["dep-1", "dep-2"], via=["svc"]),
                                     _row("code", named=["dep-1"], via=["svc"]), _row("data", "insufficient")])
    assert ok is True and "change and code specialists both name dep-1" in detail


def test_correlation_disagrees_when_the_code_channel_names_another_change():
    ok, detail = correlate("dep-1", [_row("change", named=["dep-1", "dep-2"], via=["svc"]),
                                     _row("code", named=["dep-2"], via=[])])
    assert ok is False and "code names dep-2" in detail and "confident=false" in detail
    ok, _ = correlate("dep-1", [_row("change", named=["dep-1"], via=["svc"]), _row("data", named=[], via=[])])
    assert ok is False  # the data channel completed, inspected and named nothing: it does not corroborate


def test_correlation_is_not_evaluable_without_an_artefact_channel_or_change_record():
    ok, detail = correlate("dep-1", [_row("change", named=["dep-1"], via=["svc"]), _row("code", "insufficient")])
    assert ok is None and "strict reading would downgrade" in detail
    assert correlate("dep-1", [])[0] is None
    assert correlate("dep-1", [_row("change", named=["dep-2"], via=[]), _row("code", named=["dep-1"], via=["svc"])])[0] is None


def test_g7_correlation_is_independent_of_the_gates_eliminations():
    """Review M13/M14 (M2): a code channel naming a rival is disagreement even if the gate eliminated that rival; it is
    'not evaluable' only when the cause has no code artefact to inspect (and no data channel judged it)."""
    from faultline.agent.gate import correlate

    rows = [{"role": "change", "status": "complete", "named": ["D-cause", "D-x"], "via": ["svc"]},
            {"role": "code", "status": "complete", "named": ["D-x"], "via": []}]
    ok, why = correlate("D-cause", rows, cause_has_code=True)
    assert ok is False and "D-x" in why                                # inspectable cause, rival named: disagree
    ok, why = correlate("D-cause", rows, cause_has_code=False)
    assert ok is None and "no commits or diff facts" in why            # a config change: the code channel cannot judge
    data = rows + [{"role": "data", "status": "complete", "named": [], "via": []}]
    assert correlate("D-cause", data, cause_has_code=False)[0] is False  # the data channel did judge it
    agree = rows[:1] + [{"role": "code", "status": "complete", "named": ["D-cause"], "via": ["svc"]}]
    assert correlate("D-cause", agree)[0] is True