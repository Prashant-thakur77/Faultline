"""Unit: FaultBench-OTel (evals/faultbench_otel.py): the pre-registered plan, raw counters → per-minute rates, the page
rule, the window → scenario spec, grading, report keys; and the product's observed-telemetry validation
(faultline.ingest.observed). No demo, no Prometheus, no FalkorDB."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "backend"))

import faultbench_otel as fb  # noqa: E402
import report  # noqa: E402
from faultline.ingest import observed  # noqa: E402

MIN = 60_000
T0 = 1_792_200_000_000 - (1_792_200_000_000 % MIN)   # a whole minute


def test_plan_matches_the_preregistration():
    p = fb.plan()
    assert p == fb.plan()                                   # deterministic
    assert len(p) == 20
    flags = [s["fault"]["flag"] for s in p]
    assert sorted(set(flags)) == sorted(fb.FAULTS) and all(flags.count(f) == fb.REPS for f in fb.FAULTS)
    ids = [i for s in p for w in (s["control"], s["fault"]) for i in w["ids"].values()]
    assert len(ids) == len(set(ids)) and all(i.startswith("D-") and len(i) == 10 for i in ids)
    for s in p:
        f = s["fault"]
        assert f["d1"] != f["service"] and f["d2"] in f["on_path"] and f["d3"] in f["off_path"]
        assert f["service"] not in (f["d2"], f["d3"]) and set(f["on_path"]).isdisjoint(f["off_path"])
        assert 330 <= f["flip_after_s"] <= 420 and 10 <= f["d1_before_s"] <= 840
        c = s["control"]
        assert c["d1"] == "checkout" and "checkout" not in (c["d2"], c["d3"]) and c["d2"] != c["d3"]


def _series(svc, status, values):
    return {"labels": {"service_name": svc, "span_name": "x", "status_code": status, "collector_instance_id": "i"},
            "values": values}


def test_minute_rates_counter_deltas_resets_and_new_series():
    start = T0                                                # the old series is sampled 6 s after the range opens
    ok = _series("payment", "STATUS_CODE_UNSET", [[T0 + 6_000, 100], [T0 + 66_000, 110], [T0 + 126_000, 4]])
    err = _series("payment", "STATUS_CODE_ERROR", [[T0 + 186_000, 3], [T0 + 246_000, 5]])   # born inside the range
    r = fb.minute_rates([ok, err], start)["payment"]
    # stamps are the sample time rounded UP to the minute; the reset (110 → 4) counts 4
    assert r[T0 + 2 * MIN] == [10, 0] and r[T0 + 3 * MIN] == [4, 0]
    assert r[T0 + 4 * MIN] == [3, 3] and r[T0 + 5 * MIN] == [2, 2]   # a series born inside counts from zero
    assert T0 + MIN not in r                                  # the first sample of an old series is only a reference
    assert fb.rate(r[T0 + 4 * MIN]) == pytest.approx(1.0)


def _flat(svc, minutes, calls=20, errs=None):
    """Per-minute cells for one service: errs = {minute index: errors}."""
    return {svc: {T0 + i * MIN: [float(calls), float((errs or {}).get(i, 0))] for i in range(minutes)}}


def test_page_rule():
    rates = _flat("cart", 45, errs={40: 2, 41: 1})           # 10 % then 5 %
    assert fb.page_minutes(rates, T0 + 35 * MIN, T0 + 44 * MIN) == {"cart": T0 + 40 * MIN}
    quiet = _flat("cart", 45, errs={40: 0})
    assert fb.page_minutes(quiet, T0 + 35 * MIN, T0 + 44 * MIN) == {}
    few = _flat("cart", 45, calls=4, errs={40: 4})            # 100 % of 4 calls: below the 5-call floor
    assert fb.page_minutes(few, T0 + 35 * MIN, T0 + 44 * MIN) == {}


def _samples_from_cells(cells):
    """Cumulative counters (one sample per minute, 6 s after it) reproducing per-minute cells."""
    out = []
    for svc, by in cells.items():
        ok, err, okv, errv = [], [], 0.0, 0.0
        for m in sorted(by):
            calls, errs = by[m]
            okv += calls - errs
            errv += errs
            ok.append([m - MIN + 6_000, okv])
            err.append([m - MIN + 6_000, errv])
        out += [_series(svc, "STATUS_CODE_UNSET", ok), _series(svc, "STATUS_CODE_ERROR", err)]
    return out


def _fault_window(errs):
    cells = {**_flat("payment", 50, errs=errs), **_flat("checkout", 50, errs=errs), **_flat("ad", 50)}
    flip = T0 + 38 * MIN + 20_000
    return {"wid": "otel-f99", "kind": "fault", "slot": 99, "sid": "Cabc123", "flip_window": [flip, flip + 8 * MIN],
            "range": [T0 - MIN, T0 + 50 * MIN], "samples": _samples_from_cells(cells),
            "changes": [{"change": "D-00000001", "target": "payment", "kind": "flag", "at": flip},
                        {"change": "D-00000002", "target": "checkout", "kind": "flag", "at": flip - 5 * MIN},
                        {"change": "D-00000003", "target": "frontend", "kind": "deploy", "u": 0.0},
                        {"change": "D-00000004", "target": "ad", "kind": "deploy", "u": 1.0}]}


def test_build_fault_window_spec():
    b = fb.build(_fault_window({40: 10, 41: 10, 42: 9}), 0.25)
    assert b["detected"] and b["onset"] == T0 + 40 * MIN
    s = b["spec"]
    assert {a["target"] for a in s["alerts"]} == {"payment", "checkout"} and s["onset"] == b["onset"]
    assert {c["title"] for c in s["inject"]} == {f"{c['target']}: change" for c in s["inject"]}
    ats = {c["change"]: int(c["at"][1:-1]) for c in s["inject"]}
    assert all(c["at"].startswith("-") for c in s["inject"])
    assert ats["D-00000003"] == 30 and ats["D-00000004"] == 30 + 870     # onset − 30 s − u × 14.5 min
    rows = s["observed"]["rows"]
    assert min(r["at"] for r in rows) == b["onset"] - 30 * MIN and max(r["at"] for r in rows) == b["onset"] + 5 * MIN
    assert observed.validate(rows) and "cause" not in json.dumps(s)


def test_build_undetected_and_change_after_onset():
    assert fb.build(_fault_window({}), 0.25)["detected"] is False
    w = _fault_window({40: 10})
    w["changes"][1]["at"] = T0 + 45 * MIN                      # a recorded change after the page: refused loudly
    with pytest.raises(RuntimeError):
        fb.build(w, 0.25)


def test_grade_blames():
    g = fb.grade_blames
    assert g(["D-1"], ["CONFIRMED"], "D-1") == {"right_cause": True, "wrong": False, "abstained": False,
                                                "no_incident": False, "blame_free": False}
    assert g(["D-2"], ["CONFIRMED"], "D-1")["wrong"]
    assert g(["D-1", "D-2"], ["CONFIRMED"], "D-1")["wrong"] and not g(["D-1", "D-2"], ["CONFIRMED"], "D-1")["right_cause"]
    assert g([], ["NOT_CONFIDENT"], "D-1")["abstained"] and g([], ["NO_INCIDENT"], None)["blame_free"]
    assert g([], ["NO_INCIDENT"], "D-1")["no_incident"] and not g([], ["NO_INCIDENT"], "D-1")["abstained"]


def test_observed_validation_refuses_bad_rows():
    good = [{"target": "cart", "at": T0, "value": 0.1, "calls": 10}]
    assert observed.validate(good)[0]["value"] == 0.1
    for bad in ({"target": "", "at": T0, "value": 0.1}, {"target": "cart", "at": T0 + 1, "value": 0.1},
                {"target": "cart", "at": T0, "value": 1.5}):
        with pytest.raises(observed.ObservedTelemetryError):
            observed.validate([bad])
    with pytest.raises(observed.ObservedTelemetryError):
        observed.validate(good + good)
    assert observed.digest(observed.validate(good)) == observed.digest(observed.validate(list(reversed(good))))


def _row(wid, kind, fault, fl, t, n, detected=True):
    arm = lambda right, wrong, ab, bf: {"right_cause": right, "wrong": wrong, "abstained": ab, "no_incident": False,  # noqa: E731
                                        "blame_free": bf, "right_frac": 1.0 if right else 0.0}
    return {"wid": wid, "kind": kind, "fault": fault, "detected": detected, "health": {},
            "faultline": arm(*fl), "faultline_prefix": arm(*fl), "t": arm(*t), "tplus": arm(*t), "n": arm(*n)}


def test_report_keys_and_markdown():
    rows = [_row("otel-f01", "fault", "paymentFailure", (True, False, False, False), (False, True, False, False),
                 (True, False, False, False)),
            _row("otel-f02", "fault", "cartFailure", (False, False, True, True), (True, False, False, False),
                 (False, True, False, False)),
            _row("otel-f03", "fault", "cartFailure", (False, False, False, True), (False, False, False, True),
                 (False, False, False, True), detected=False),
            _row("otel-c01", "control", None, (False, False, False, True), (False, True, False, False),
                 (False, True, False, False))]
    k = report.faultbench_otel_keys({"rows": rows, "demo": "3.1.0", "seed": 1}, {"n": 3, "est_usd": 0.5})
    assert k["otel.detected"] == 2 and k["otel.controls"] == 1 and k["otel.scored"] == 3
    assert k["otel.faultline.right_cause.k"] == 1 and k["otel.faultline.right_cause.n"] == 2
    assert k["otel.faultline.wrong.k"] == 0 and k["otel.faultline.wrong.n"] == 3
    assert k["otel.T.wrong"] == 2 and k["otel.faultline.control_blame_free.k"] == 1
    assert k["otel.fault.cartFailure.windows"] == 2 and k["otel.fault.cartFailure.detected"] == 1
    md = "\n".join(report.faultbench_otel_markdown(k))
    assert "FaultBench-OTel" in md and "| Faultline | 1/2" in md and "cartFailure | 2 | 1 |" in md
    assert k["otel.faultline_prefix.right_cause.k"] == 1 and "Faultline as registered" in md


def test_zero_baseline_rise_is_anomalous_and_the_registered_rule_is_kept_for_the_eval():
    from faultline.agent import datatools

    assert datatools.error_rate_anomalous(0.1, 0.0, 1.2)            # a rise from exactly zero: outside every band
    assert not datatools.error_rate_anomalous(0.005, 0.0, 1.2)      # below err_abs_min: in band
    assert datatools.error_rate_anomalous(0.05, 0.01, 1.2) and not datatools.error_rate_anomalous(0.0105, 0.01, 1.2)
    assert not fb._prefix_rule(0.1, 0.0, 1.2)                       # the rule as registered missed it
    assert fb._prefix_rule(0.05, 0.01, 1.2)


def test_broken_baseline_is_excluded():
    w = _fault_window({40: 10})
    assert fb.baseline_broken(w) == {}
    broken = _fault_window({i: 20 for i in range(0, 50)})          # payment and checkout failing 100 % all along
    assert set(fb.baseline_broken(broken)) == {"payment", "checkout"}
    rows = [_row("otel-f01", "fault", "cartFailure", (True, False, False, False), (True, False, False, False),
                 (True, False, False, False)), {**_row("otel-f02", "fault", "cartFailure", (False,) * 4, (False,) * 4,
                                                       (False,) * 4, detected=False), "excluded": "infrastructure"}]
    k = report.faultbench_otel_keys({"rows": rows, "demo": "3.1.0", "seed": 1}, {})
    assert k["otel.excluded"] == 1 and k["otel.fault_windows"] == 1 and k["otel.fault.cartFailure.windows"] == 1
