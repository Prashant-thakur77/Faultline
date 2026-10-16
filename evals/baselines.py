"""Telemetry-only comparators on generated bench worlds (eval-side only; never in the product).

T   the window's change whose own component shows the largest error-rate excess; it never abstains (evals/harness.py)
T+  T with a floor (PREREGISTRATION amendment 2026-10-16): NO_INCIDENT when no alerting symptom is above
    gate.err_abs_min, NOT_CONFIDENT when no changed component is, else the largest excess (ties reported, 1/k)

`both(case)` prepares the world once and returns both blames; `score(...)` grades them against the bench's expected
verdict: right (strict: the single top change is the cause; fractional: 1/k on a tie), wrong (any blame of another
change, or any blame where nothing should be blamed), abstained.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT / "evals") not in sys.path:
    sys.path.insert(0, str(ROOT / "evals"))

from faultline import scenario  # noqa: E402
from faultline.graph import client as gclient  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402


def both(case: dict) -> dict:
    from harness import excess_of, telemetry_plus_decision

    spec = case["spec"]
    p = scenario.prepare(spec["id"], tag=uuid.uuid4().hex[:8], set_mode=False, spec=spec)
    try:
        ro = RO(p.tenant, p.graph)
        win = int(spec.get("window_min") or 30)
        changes = ro.run("Q-SUS-2", {"onset": p.onset_ms, "window_ms": win * 60_000}).rows
        exc = {c["deploy"]: excess_of(ro, c["target"], p.onset_ms) for c in changes}
        sym = [excess_of(ro, s, p.onset_ms) for s in p.symptoms]
    finally:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    vals = {c: (e if e is not None else 0.0) for c, e in exc.items()}
    best = max(vals.values()) if vals else None
    t_tied = sorted(c for c, v in vals.items() if v == best) if vals else []
    tp = telemetry_plus_decision(sym, exc)
    return {"t": {"outcome": "CONFIRMED" if t_tied else "NO_INCIDENT", "tied": t_tied},
            "tplus": {"outcome": tp["outcome"], "tied": tp["tied"]}}


def score(expected: dict, blame: dict) -> dict:
    """{right_strict, right_frac, wrong_frac, blamed, abstained} for one comparator's blame on one world."""
    tied, cause = blame["tied"], expected.get("cause")
    blamed = bool(tied)
    if expected["outcome"] == "CONFIRMED":
        frac = (1.0 / len(tied)) if cause in tied else 0.0
        return {"right_strict": tied == [cause], "right_frac": round(frac, 4), "wrong_frac": round(1.0 - frac, 4) if blamed else 0.0,
                "blamed": blamed, "abstained": not blamed}
    return {"right_strict": not blamed, "right_frac": 0.0 if blamed else 1.0, "wrong_frac": 1.0 if blamed else 0.0,
            "blamed": blamed, "abstained": not blamed}
