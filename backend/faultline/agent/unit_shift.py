"""A measured data repair, with no model and no knowledge of any scenario (track T1: the agent acts on what the
data and the graph show).

After the gate has confirmed a data cutover as the cause, the keyless run can still propose the repair a human then
approves: the warehouse is asked whether the anomalous column's bad rows are ONE segment (one value of one text
column) whose values are a power of ten off the healthy ones (datatools.unit_shift_check, recorded as Evidence), and
the transform that writes the table (the graph's WRITES edge) gets that column wrapped in a CASE that divides only
that segment's rows. Everything here is a pure function of the measured numbers and the transform's text:

* `find_shift`: the decision rule over the per-segment statistics;
* `scoped_fix`: the transform's output column expression, scoped to the segment;
* `explain`: the reasoning line the plan shows, citing the evidence.

The proposal is only a proposal: two-step approval of the exact diff, then the rebuild, the invariant suite and the
KPI decide whether it worked (actions/act.py::_verify_data_repair); a wrong one is reverted, never written as success.
"""

from __future__ import annotations

import math
import re

_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_VALUE = re.compile(r"^[A-Za-z0-9_.:+\- /]{1,64}$")


def find_shift(segments: list[dict], *, tolerance: float, purity: float, min_rows: int) -> dict | None:
    """The one segment whose rows carry the anomaly as a unit shift, or None.

    Each row of `segments` describes one value of one text column on the measured day: `n` rows, `outside` of them
    outside the column's healthy range, their `median`; the complement (the other values of that column, on the day
    when it has rows, else the days before) as `other_n`, `other_outside`, `other_median`; and `total_outside`, the
    table's outside rows that day. A segment qualifies when it is nearly all outside (outside / n ≥ purity), holds
    nearly all the outside rows (outside / total_outside ≥ purity), its complement is nearly all inside
    (other_outside / other_n ≤ 1 − purity), and its median is 10^k (k = 1..4) times the complement's within
    `tolerance`. A segment whose value did not exist before the shift began (`existed_before` false) is preferred:
    it appeared with the anomaly. Then the best coverage, then purity. Two segments that fit equally (every row of
    the day shares both values) are no answer: None, so nothing is proposed by guesswork."""
    found: list[tuple] = []
    for s in sorted(segments, key=lambda s: (str(s.get("segment")), str(s.get("value")))):
        n, out, tot = int(s.get("n") or 0), int(s.get("outside") or 0), int(s.get("total_outside") or 0)
        on, oo = int(s.get("other_n") or 0), int(s.get("other_outside") or 0)
        med, other = s.get("median"), s.get("other_median")
        if n < min_rows or tot <= 0 or on <= 0 or med is None or other is None or float(other) <= 0:
            continue
        pur, cov, clean = out / n, out / tot, 1 - oo / on
        if pur < purity or cov < purity or clean < purity:
            continue
        factor = float(med) / float(other)
        if factor <= 1:
            continue
        power = int(round(math.log10(factor)))
        if not 1 <= power <= 4 or abs(factor / 10 ** power - 1) > tolerance:
            continue
        existed = bool(s.get("existed_before"))
        hit = {"segment": s["segment"], "value": s["value"], "n": n, "outside": out, "purity": round(pur, 4),
               "coverage": round(cov, 4), "complement_clean": round(clean, 4), "median": float(med),
               "other_median": float(other), "factor": round(factor, 4), "power": power,
               "since_day": s.get("since_day"), "existed_before": existed}
        # a value that appeared with the anomaly explains it better than one that was there, healthy, before
        found.append(((not existed, cov, pur), hit))
    if not found:
        return None
    found.sort(key=lambda x: x[0], reverse=True)
    if len(found) > 1 and found[0][0] == found[1][0]:
        return None   # two segments fit equally (every row of the day shares both values): no guess, nothing proposed
    return found[0][1]


def scoped_fix(sql: str, column: str, segment: str, value: str, power: int, *, since_day: str | None = None,
               ts_expr: str | None = None) -> str | None:
    """The transform's SQL with its `column` output expression wrapped in a CASE that divides only the segment's
    rows by 10^power (and, when `since_day` and `ts_expr` are given, only rows from that day on). Returns None when
    the transform does not define the column as exactly one `<expr> AS <column>` line, so nothing is rewritten by
    guesswork. Identifiers are validated and the value is a quoted literal (quotes doubled)."""
    if not (_IDENT.match(column) and _IDENT.match(segment) and _VALUE.match(value) and 1 <= int(power) <= 4):
        return None
    pat = re.compile(rf"^(?P<indent>[ \t]*)(?P<expr>\S.*?)[ \t]+AS[ \t]+{re.escape(column)}(?P<tail>[ \t]*,?[ \t]*)$",
                     re.I | re.M)
    hits = [m for m in pat.finditer(sql) if not m.group("expr").lstrip().startswith("--")]
    if len(hits) != 1:
        return None
    m = hits[0]
    expr = m.group("expr").strip()
    if expr.upper().startswith("CASE WHEN"):
        return None   # already scoped once: a second wrap would hide the first
    when = f"{segment} = '{value.replace(chr(39), chr(39) * 2)}'"
    # the date clause only when the time column is a name the transform's own SELECT can see (a transform that
    # renames its time column gets the segment-only fix, and the reasoning says so)
    if (since_day and ts_expr and re.fullmatch(r"\d{4}-\d{2}-\d{2}", since_day) and _IDENT.match(ts_expr)
            and re.search(rf"\b{re.escape(ts_expr)}\b", sql)):
        when += f" AND CAST({ts_expr} AS TIMESTAMP) >= TIMESTAMP '{since_day} 00:00:00'"
    new = f"{m.group('indent')}CASE WHEN {when} THEN ({expr}) / {10 ** int(power)} ELSE {expr} END AS {column}{m.group('tail')}"
    return sql[: m.start()] + new + sql[m.end():]


def explain(hit: dict, table: str, column: str, file: str, evidence_ids: list[str], *, dated: bool | None = None) -> str:
    """One line a reviewer can check against the evidence: what was measured, and what the patch does. `dated`: whether
    the patch carries the date clause (None: as the measurement would have it)."""
    scope = f"{hit['segment']} = {hit['value']!r}"
    if hit.get("since_day") and hit.get("existed_before"):
        if dated or dated is None:
            scope += f" from {hit['since_day']}"
        else:
            scope += f" (healthy before {hit['since_day']}; the transform does not expose a time column, so every row of the segment is divided)"
    return (f"unit shift measured on {table}.{column}: the {hit['n']} rows with {scope} are {hit['purity']:.0%} outside "
            f"the healthy range and hold {hit['coverage']:.0%} of the outside rows; their median {hit['median']:,.2f} is "
            f"{hit['factor']:.1f}× the other rows' {hit['other_median']:,.2f}, a 10^{hit['power']} unit shift. "
            f"{file} divides only those rows by {10 ** hit['power']}; nothing else changes. Evidence: "
            + ", ".join(evidence_ids))


__all__ = ["find_shift", "scoped_fix", "explain"]
