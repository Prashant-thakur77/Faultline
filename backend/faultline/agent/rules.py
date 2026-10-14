"""Decision rule evaluation (shared by G8 decision_check and preflight). The graph selects which active,
non-superseded decisions constrain which asserted facts (Q-DEC-1); this only compares a value to a rule."""

from __future__ import annotations

from typing import Any

OPS = {"<=": lambda x, y: x <= y, ">=": lambda x, y: x >= y, "==": lambda x, y: x == y, "<": lambda x, y: x < y,
       ">": lambda x, y: x > y, "!=": lambda x, y: x != y}


def num(v: Any) -> Any:
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    return float(v)


def violated(op: str | None, actual: Any, expected: Any) -> bool | None:
    """True/False, or None when it cannot be decided (surfaced to a human, never silently passed)."""
    f = OPS.get(op or "")
    if f is None:
        return actual in (None, "")
    try:
        return not f(num(actual), num(expected))
    except (TypeError, ValueError):
        if op in ("==", "!=") and actual is not None and expected is not None:   # equality is defined on text too
            same = str(actual).strip().lower() == str(expected).strip().lower()
            return (not same) if op == "==" else same
        return None   # an ordering on text cannot be decided: surfaced to a human, never silently passed


OVERRIDE_VERDICTS = ("intentional", "accidental", "discuss")


def apply_override(row: dict) -> dict:
    """A reviewer's answer to a contradiction, for THIS change (M15 #3, Q-DEC-1's `override` column). `intentional`:
    the change deliberately departs from the decision, so it is no longer reported as a violation (kept as
    `violated_raw` and shown as an accepted deviation with who and why). `accidental` and `discuss` keep the violation.
    One rule for G8 and preflight, so the two never disagree."""
    o = row.get("override") or None
    row["violated_raw"] = row.get("violated")
    row["overridden"] = bool(o and o.get("verdict") == "intentional" and row.get("violated"))
    if row["overridden"]:
        row["violated"] = False
    return row


def reversals(rows: list[dict]) -> list[dict]:
    """Reversal guard (Q-DEC-REV rows → findings): the change reinstates a decision the org later reversed when its
    value satisfies the SUPERSEDED rule (decided here, as for Q-DEC-1). Each finding names the decision in force and
    what it cites (why it was reversed). Annotation only: never a gate check, never a preflight score term."""
    out = []
    for r in rows:
        if violated(r.get("op"), r.get("actual"), r.get("old_value")) is False:   # it matches what was reversed
            out.append({"reversed": r["reversed"], "reversed_title": r.get("reversed_title"), "rule_key": r.get("rule_key"),
                        "actual": r.get("actual_text"), "about": r.get("about"), "head": r["head"],
                        "head_title": r.get("head_title"), "head_decided_at": r.get("head_decided_at"),
                        "head_url": r.get("head_url"), "because": r.get("because") or []})
    return out
