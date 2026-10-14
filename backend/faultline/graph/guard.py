"""Guarded text2cypher: the LAST resort, after full-text/vector seeds and templates.

guard(query) works on the query with string literals masked, so keywords hidden in strings neither pass nor
trip the checks. It rejects:
* comments and multiple statements;
* raw GRAPH.* commands;
* write clauses, UNION and LOAD CSV;
* CALLs outside the registry's read algorithms and the index query procedures;
* unbounded variable-length patterns;
* the private-data policy (review round 5, minor 6): the Session and Turn labels, the HAS_TURN relationship, the
  Run.token_sha property and the Turn/Session-only properties (text, refs, user), in any form (`:Session`, `n.text`,
  `{.token_sha}`, `{user: …}`, `n['text']`, `'Turn' IN labels(n)`), and `properties(…)` (it would return them all).
  The rows that come back are filtered too (`redact_rows`): a whole Session/Turn node, a server-issued session id
  (`sess-…`) and a denied property never reach the caller, whatever the query looked like.
It also caps or appends LIMIT ≤ 100. explain_check() then runs GRAPH.EXPLAIN through the read-only user and
rejects plans with a Cartesian product over two or more full scans. The query finally runs through RO.run_guarded
(GRAPH.RO_QUERY, 3 s timeout, ACL read-only user). Three independent layers: guard, read-only command, ACL.
"""

from __future__ import annotations

import re

from .algo import registry
from .templates import mask_strings

MAX_LIMIT = 100
TIMEOUT_MS = 3000

WRITE_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD|UNION)\b", re.I)
CALL_RE = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)", re.I)
GRAPH_CMD_RE = re.compile(r"\bGRAPH\s*\.", re.I)
COMMENT_RE = re.compile(r"//|/\*")
# the range may be followed by `]` OR by a property map (`*1..99 {k:''}]`): both forms reached the engine unchecked
# before (review round 4, M6). check_plan also rejects any plan the engine reads as unbounded (`..INF`).
VARLEN_RE = re.compile(r"\[[^\]]*?\*\s*(\d*)\s*(\.\.)?\s*(\d*)\s*(?=[\]{])")
LIMIT_END_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.I)
LIMIT_ANY_RE = re.compile(r"\bLIMIT\b", re.I)


class GuardError(ValueError):
    """The query is not allowed (reason in the message)."""


# private data no guarded query may read (brain sessions and turns are per user; a run token hash is a capability)
DENY_LABELS = ("Session", "Turn")
DENY_RELS = ("HAS_TURN",)
DENY_PROPS = ("token_sha", "text", "refs", "user")
_DENY_NAMES = {x.lower() for x in DENY_LABELS + DENY_RELS + DENY_PROPS}
_LABEL_RE = re.compile(r":\s*`?(" + "|".join(DENY_LABELS + DENY_RELS) + r")\b", re.I)
_PROP_RE = re.compile(r"\.\s*`?(" + "|".join(DENY_PROPS) + r")\b(?!\s*[.(])", re.I)
_MAPKEY_RE = re.compile(r"[{,]\s*`?(" + "|".join(DENY_PROPS) + r")`?\s*:", re.I)
_PROPS_FN_RE = re.compile(r"\bproperties\s*\(", re.I)
_STRING_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")


def check_private(q: str, masked: str) -> None:
    """The private-data policy on the query text (strings masked for syntax; literals checked on their own)."""
    for rx, what in ((_LABEL_RE, "label/relationship"), (_PROP_RE, "property"), (_MAPKEY_RE, "property")):
        m = rx.search(masked)
        if m:
            raise GuardError(f"{what} {m.group(1)} is private (brain sessions, turns and run tokens are not queryable)")
    if _PROPS_FN_RE.search(masked):
        raise GuardError("properties(…) is not allowed (it would return private properties); name the properties")
    if re.search(r"\[\s*\$", masked):
        raise GuardError("dynamic property access (n[$param]) is not allowed; name the properties")
    for m in _STRING_RE.finditer(q):
        lit = (m.group(1) if m.group(1) is not None else m.group(2) or "").strip().lower()
        if lit in _DENY_NAMES or lit.startswith("sess-"):
            raise GuardError(f"the literal {lit!r} names private data (brain sessions, turns and run tokens)")


def check_params(params: dict | None) -> None:
    """A parameter value may not name private data either (it could be compared with labels(n) or keys(n))."""
    def walk(v) -> None:
        if isinstance(v, str) and (v.strip().lower() in _DENY_NAMES or v.strip().lower().startswith("sess-")):
            raise GuardError(f"the parameter value {v!r} names private data (brain sessions, turns and run tokens)")
        if isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
    walk(params or {})


def _private_value(v) -> bool:
    if isinstance(v, str):
        return v.startswith("sess-")
    if isinstance(v, dict):
        if set(v.get("_labels") or []) & set(DENY_LABELS) or v.get("_type") in DENY_RELS:
            return True
        return any(_private_value(x) for k, x in v.items() if k not in DENY_PROPS)
    if isinstance(v, list):
        return any(_private_value(x) for x in v)
    return False


def _strip(v):
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if k not in DENY_PROPS}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    return v


def redact_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Drop every row that carries a Session/Turn node, a HAS_TURN edge or a session id, and strip the denied
    properties from every entity map. Returns (rows, how many rows were dropped)."""
    out = [_strip(r) for r in rows if not any(_private_value(x) for x in r.values())]
    return out, len(rows) - len(out)


def guard(query: str, max_limit: int = MAX_LIMIT) -> str:
    if not isinstance(query, str) or not query.strip():
        raise GuardError("empty query")
    if len(query) > 4000:
        raise GuardError("query too long (max 4000 chars)")
    q = query.strip()
    while q.endswith(";"):
        q = q[:-1].rstrip()
    m = mask_strings(q)
    if ";" in m:
        raise GuardError("single statement only")
    if COMMENT_RE.search(m):
        raise GuardError("comments are not allowed")
    if GRAPH_CMD_RE.search(m):
        raise GuardError("raw GRAPH.* commands are not allowed")
    w = WRITE_RE.search(m)
    if w:
        raise GuardError(f"write/unsupported keyword {w.group(1).upper()} is not allowed")
    check_private(q, m)
    allowed = registry.allowed_procedures()
    for name in CALL_RE.findall(m):
        if name.lower() not in allowed:
            raise GuardError(f"procedure {name} is not allowed")
    for lo, dots, hi in VARLEN_RE.findall(m):
        if (dots and not hi) or (not dots and not lo):
            raise GuardError("unbounded variable-length pattern; give an upper bound (e.g. *1..4)")
        if int(hi or lo) > 8:
            raise GuardError("variable-length upper bound must be ≤ 8")
    lim = LIMIT_END_RE.search(m)
    if lim is None:
        if LIMIT_ANY_RE.search(m):
            raise GuardError("LIMIT must be a literal integer at the end of the query")
        return f"{q} LIMIT {max_limit}"
    if int(lim.group(1)) > max_limit:
        raise GuardError(f"LIMIT must be ≤ {max_limit}")
    return q


_SCAN = re.compile(r"(All Node Scan|Node By Label Scan)")


def check_plan(plan_lines: list[str]) -> None:
    """Reject a Cartesian product whose branches are two or more full scans (an accidental cross join)."""
    text = "\n".join(plan_lines)
    if re.search(r"\.\.\s*INF\b", text):
        raise GuardError("plan has an unbounded variable-length traversal; give an upper bound (e.g. *1..4)")
    if "Cartesian Product" in text and len(_SCAN.findall(text)) >= 2:
        idx = next(i for i, ln in enumerate(plan_lines) if "Cartesian Product" in ln)
        depth = len(plan_lines[idx]) - len(plan_lines[idx].lstrip())
        below = [ln for ln in plan_lines[idx + 1:] if len(ln) - len(ln.lstrip()) > depth]
        if len([ln for ln in below if _SCAN.search(ln)]) >= 2 and not any("Filter" in ln for ln in below[:2]):
            raise GuardError("plan has a Cartesian product over full scans; anchor the pattern on an id or connect it")


__all__ = ["guard", "check_plan", "check_private", "check_params", "redact_rows", "GuardError", "MAX_LIMIT", "TIMEOUT_MS",
           "DENY_LABELS", "DENY_PROPS", "DENY_RELS"]
