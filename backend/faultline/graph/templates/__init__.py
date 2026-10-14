"""Cypher template loader + lint. Every read the product makes is one of these files.

File format (`templates/*.cypher`):

    // id: Q-GATE-1
    // purpose: the load-bearing proof path (gate G2)
    // returns: rows            (or: single-row)
    // seen: chain              (columns whose ids count as "seen in a graph result" for grounding)
    MATCH (c:Node {id:$cause}) ... CALL {algo:sppaths}({...}) ...
    RETURN ... ORDER BY ..., id
    LIMIT 3

Rules enforced at load time (TemplateLintError, fail loudly):
* ends with a literal `LIMIT n`, 1 ≤ n ≤ 100; no parameter/expression in LIMIT/SKIP; no UNION;
* `ORDER BY` present unless `returns: single-row` (deterministic demos);
* every variable-length pattern has an upper bound (`*1..6`, never `*`, `*1..` or `*{…}` unbounded);
* `CALL` only for `{algo:<key>}` (resolved from the registry), db.idx.fulltext/vector.queryNodes, the
  schema-introspection procedures db.meta.stats / db.indexes, and read subqueries `CALL { … }` (whose inner CALLs
  obey the same allowlist);
* no write clauses and no literal `algo.` names;
* `WHERE` inside an `OPTIONAL MATCH` clause must be marked `// lint: optional-where-ok`;
* a `seen` column must not simply echo a parameter (`$x AS col`), so model-supplied ids never count as seen.
Execution: the final `LIMIT n` is sent as `LIMIT n+1` so the RO wrapper can detect truncation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..algo import registry

TEMPLATE_DIR = Path(__file__).parent
MAX_LIMIT = 100
MARKER = "lint: optional-where-ok"

_HEADER = re.compile(r"^//\s*(\w[\w-]*)\s*:\s*(.*?)\s*$")
_LIMIT_END = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.I)
_BAD_LIMIT = re.compile(r"\b(LIMIT|SKIP)\s+(?!\d+\b)", re.I)
_VARLEN = re.compile(r"\*\s*(\d*)\s*(\.\.)?\s*(\d*)\s*(?=[\]{])")
_ALGO_PH = re.compile(r"\{algo:([a-z_]+)\}")
_WRITE = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|FOREACH|LOAD)\b", re.I)
_CALL = re.compile(r"\bCALL\s+([^\s(]+)", re.I)
# index queries, plus the read-only schema-introspection procedures (mode READ in dbms.procedures on 6.0.2;
# verified under GRAPH.RO_QUERY by smoke item 24)
_ALLOWED_CALLS = {"db.idx.fulltext.querynodes", "db.idx.vector.querynodes", "db.meta.stats", "db.indexes"}
_AGG = re.compile(r"\b(collect|count|sum|min|max|avg)\s*\(", re.I)
_COMP = re.compile(r"\[\s*(?:\w+\s*=\s*)?\((?:[^\[\]]|\[[^\[\]]*\])*\|")       # [(…) | , [ (…) | , [p = (…) |
_NAMED_REL = re.compile(r"-\[\s*(\w+)\s*[:\]*{]")                                  # -[r:T], -[r], -[r*1..2]
_CLAUSE = re.compile(r"\b(OPTIONAL\s+MATCH|MATCH|WITH|RETURN|UNWIND|CALL|ORDER\s+BY)\b", re.I)


class TemplateLintError(ValueError):
    pass


class UnknownTemplate(KeyError):
    pass


@dataclass(frozen=True)
class Template:
    id: str
    purpose: str
    returns: str
    text: str            # executable text (LIMIT n+1)
    display: str         # the text shown to people (LIMIT n)
    limit: int
    path: str
    seen: tuple[str, ...] = field(default_factory=tuple)


def mask_strings(s: str) -> str:
    """Replace string-literal contents with spaces (keeps offsets; quotes kept)."""
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", lambda m: m.group(0)[0] + " " * (len(m.group(0)) - 2) + m.group(0)[-1], s)


def strip_comments(s: str) -> str:
    """Remove `// …` comments that are outside string literals."""
    masked = mask_strings(s)
    out, i = [], 0
    for m in re.finditer(r"//[^\n]*", masked):
        out.append(s[i : m.start()])
        i = m.end()
    out.append(s[i:])
    return re.sub(r"[ \t]+\n", "\n", "".join(out))


def inline_map_after_match(query: str) -> bool:
    """Engine bug #18 (docs/upstream/18): a MATCH right after a MATCH whose node map reads a variable's property. Used by
    the template lint and by the test that checks every write query in graph/writes.py (strings masked by the caller)."""
    n = re.sub(r"\s+", " ", query)
    kws = list(re.finditer(r"\b(OPTIONAL MATCH|MATCH|WITH|RETURN|UNWIND|CALL|ORDER BY|MERGE|CREATE|SET|DELETE)\b", n, re.I))
    spans = [(k.group(1).upper(), k.start(), kws[i + 1].start() if i + 1 < len(kws) else len(n)) for i, k in enumerate(kws)]
    for i, (kw, a, b) in enumerate(spans):
        if kw == "MATCH" and i > 0 and spans[i - 1][0] in ("MATCH", "OPTIONAL MATCH"):
            if re.search(r"\(\s*\w*\s*(?::\s*[\w`]+\s*)*\{[^}]*:\s*[A-Za-z_]\w*\.\w+", n[a:b]):
                return True
    return False


def lint(tid: str, raw_body: str, returns: str, seen: tuple[str, ...]) -> tuple[str, int]:
    """Lint a template body (comments included, for markers). Returns (code, limit)."""
    code = strip_comments(raw_body).strip()
    m_code = mask_strings(code)
    m = _LIMIT_END.search(m_code)
    if not m:
        raise TemplateLintError(f"{tid}: must end with a literal LIMIT")
    limit = int(m.group(1))
    if not 1 <= limit <= MAX_LIMIT:
        raise TemplateLintError(f"{tid}: LIMIT must be 1..{MAX_LIMIT}")
    if _BAD_LIMIT.search(m_code):
        raise TemplateLintError(f"{tid}: LIMIT/SKIP must be literal integers")
    if re.search(r"\bUNION\b", m_code, re.I):
        raise TemplateLintError(f"{tid}: UNION is not allowed in templates")
    if returns != "single-row" and not re.search(r"\bORDER\s+BY\b", m_code, re.I):
        raise TemplateLintError(f"{tid}: ORDER BY required (or declare `returns: single-row`)")
    for lo, dots, hi in _VARLEN.findall(m_code):
        if (dots and not hi) or (not dots and not lo):
            raise TemplateLintError(f"{tid}: unbounded variable-length pattern")
    if re.search(r"\balgo\.", m_code):
        raise TemplateLintError(f"{tid}: use {{algo:<key>}} placeholders, not literal procedure names")
    if _WRITE.search(m_code):
        raise TemplateLintError(f"{tid}: write clause in a read template")
    for name in _CALL.findall(m_code):
        # `CALL { … }` is a read subquery (its inner CALLs are matched and checked on their own); it is how a template
        # keeps its row when an algorithm yields nothing (algo.BFS with no reachable node returns zero rows)
        if name == "{":
            continue
        if not name.startswith("{algo:") and name.lower() not in _ALLOWED_CALLS:
            raise TemplateLintError(f"{tid}: CALL {name} not allowed (only {{algo:*}} and index queries)")
    # WHERE inside an OPTIONAL MATCH clause needs an explicit marker (raw text, strings masked)
    masked_raw = mask_strings(raw_body)
    for om in re.finditer(r"\bOPTIONAL\s+MATCH\b", masked_raw, re.I):
        nxt = _CLAUSE.search(masked_raw, om.end())
        span_end = nxt.start() if nxt else len(masked_raw)
        span = masked_raw[om.start() : span_end]
        if re.search(r"\bWHERE\b", strip_comments(span), re.I) and MARKER not in raw_body[om.start() : span_end]:
            raise TemplateLintError(f"{tid}: WHERE in an OPTIONAL MATCH clause needs `// {MARKER}`")
    # Engine-bug rules (FalkorDB 6.0.2) run on whitespace-normalised text split into clauses, so a WITH whose aggregate
    # sits on a continuation line, `[ (` / `[p = (` comprehensions and untyped relationship variables are all caught.
    n = re.sub(r"\s+", " ", m_code)
    kws = list(re.finditer(r"\b(OPTIONAL MATCH|MATCH|WITH|RETURN|UNWIND|CALL|ORDER BY)\b", n, re.I))
    spans = [(k.group(1).upper(), k.start(), kws[i + 1].start() if i + 1 < len(kws) else len(n)) for i, k in enumerate(kws)]
    agg_at = next((a + m.start() for kw, a, b in spans if kw == "WITH" for m in [_AGG.search(n[a:b])] if m), None)
    # an OPTIONAL MATCH after an aggregating WITH returns no rows (docs/upstream/07)
    if agg_at is not None and re.search(r"\bOPTIONAL MATCH\b", n[agg_at:], re.I):
        raise TemplateLintError(f"{tid}: OPTIONAL MATCH after an aggregating WITH (engine bug); use a pattern comprehension")
    # a pattern comprehension filtering on a RELATIONSHIP variable returns empty when another comprehension follows it
    # in the same projection (docs/upstream/09)
    comps = _COMP.findall(n)
    if len(comps) > 1 and any(re.search(r"-\[\s*\w+\s*[:\]*{][^|]*\bWHERE\b[^|]*\b(\w+)\.", c) for c in comps):
        raise TemplateLintError(f"{tid}: several pattern comprehensions with a relationship-variable filter (engine bug); split the template")
    # the same bug, narrower trigger: a comprehension that merely NAMES a relationship variable (typed or not) empties
    # every later comprehension of the same projection; give it its own WITH clause (docs/upstream/09)
    for kw, a, b in spans:
        if kw in ("WITH", "RETURN") and any(_NAMED_REL.search(c) for c in _COMP.findall(n[a:b])[:-1]):
            raise TemplateLintError(f"{tid}: a comprehension naming a relationship variable is followed by another in the "
                                    "same projection (engine bug); move it to its own WITH clause")
    # after an aggregating WITH, a pattern comprehension whose WHERE mixes a relationship-variable predicate with a
    # node-variable predicate returns [] (docs/upstream/11); filter nodes in an outer list comprehension
    if agg_at is not None:
        for c in _COMP.findall(n[agg_at:]):
            rel_vars = set(_NAMED_REL.findall(c))
            where = c.split("WHERE", 1)[1] if "WHERE" in c else ""
            used = set(re.findall(r"\b(\w+)\.", where))
            if rel_vars & used and used - rel_vars:
                raise TemplateLintError(f"{tid}: comprehension mixes relationship- and node-variable filters after an "
                                        "aggregating WITH (engine bug); filter nodes in an outer list comprehension")
        # the only shape observed to work after an aggregating WITH (docs/upstream/13): ONE MATCH clause before the
        # aggregation (no OPTIONAL MATCH, no second MATCH) and a comprehension WHERE on relationship variables only. A
        # node-only WHERE, or any extra (OPTIONAL) MATCH before the aggregation, silently returns []
        matches_before = sum(1 for kw, a, _ in spans if kw in ("MATCH", "OPTIONAL MATCH") and a < agg_at)
        for c in _COMP.findall(n[agg_at:]):
            if "WHERE" not in c:
                continue
            rel_vars = set(_NAMED_REL.findall(c))
            used = set(re.findall(r"\b(\w+)\.", c.split("WHERE", 1)[1]))
            if matches_before != 1 or not used or not used <= rel_vars:
                raise TemplateLintError(f"{tid}: a filtered pattern comprehension after an aggregating WITH needs a single "
                                        "MATCH before the aggregation and relationship-variable predicates only (engine "
                                        "bug, docs/upstream/13); filter nodes in an outer list comprehension")
    # FalkorDB 6.0.2: WITH/UNWIND followed by two MATCH clauses, where the first MATCH uses none of the carried
    # variables, silently drops the carried rows (docs/upstream/16); bind the first MATCH to a carried variable
    for i, (kw, a, b) in enumerate(spans):
        if kw in ("WITH", "UNWIND") and i + 2 < len(spans) and spans[i + 1][0] == "MATCH" and spans[i + 2][0] == "MATCH":
            proj = n[a:b]
            carried = set(re.findall(r"\bAS\s+(\w+)", proj, re.I))
            if kw == "WITH":
                head = re.split(r"\bWHERE\b", proj[4:], maxsplit=1, flags=re.I)[0]
                carried |= {t.strip() for t in head.split(",") if re.fullmatch(r"\s*\w+\s*", t)}
            m1 = n[spans[i + 1][1]:spans[i + 1][2]]
            if carried and not any(re.search(rf"\b{re.escape(v)}\b", m1) for v in carried):
                raise TemplateLintError(f"{tid}: {kw} followed by two MATCH clauses whose first ignores the carried "
                                        "variables (engine bug #16 drops the rows); bind it to a carried variable")
    # FalkorDB 6.0.2: after a top-level OPTIONAL MATCH, a CALL {} subquery's WHERE on a node its own pattern binds can
    # be planned below the traversal that binds it and silently filter every row (docs/upstream/17); read the optional
    # part in its own subquery instead
    depth, top_optional = 0, False
    for tok in re.finditer(r"\{|\}|\bOPTIONAL\s+MATCH\b|\bCALL\s*\{", n, re.I):
        t = tok.group(0).upper()
        if t.startswith("CALL"):
            if depth == 0 and top_optional:
                d, j = 1, tok.end()
                while j < len(n) and d:
                    d += {"{": 1, "}": -1}.get(n[j], 0)
                    j += 1
                sub = n[tok.end():j]  # a WHERE, or an inline property map on a node it binds (the same filter)
                if re.search(r"\bWHERE\b", sub, re.I) or re.search(r"\(\s*\w*\s*:\s*[\w`]+\s*\{", sub):
                    raise TemplateLintError(f"{tid}: a CALL subquery with a filter after a top-level OPTIONAL MATCH (engine bug "
                                            "#17 can drop every row); read the optional part in its own subquery")
            depth += 1
        elif t == "{":
            depth += 1
        elif t == "}":
            depth -= 1
        elif depth == 0:
            top_optional = True
    # FalkorDB 6.0.2: a top-level MATCH after a CALL {} subquery ignores a node variable bound before the subquery and
    # matches every node in its place (docs/upstream/19, found by the deep bench); MATCH first, then the subqueries
    sub = next((s for s in re.finditer(r"\bCALL\s*\{(?!\s*algo:)", n, re.I) if n[:s.start()].count("{") == n[:s.start()].count("}")), None)
    if sub:
        before = n[:sub.start()]
        bound = set(re.findall(r"\(\s*([A-Za-z_]\w*)", before)) | set(re.findall(r"\bAS\s+([A-Za-z_]\w*)", before, re.I))
        for mm in re.finditer(r"\b(?:OPTIONAL\s+)?MATCH\b", n[sub.end():], re.I):
            at = sub.end() + mm.start()
            if n[:at].count("{") != n[:at].count("}"):
                continue  # inside a subquery: its own WITH imports are fine
            nxt = _CLAUSE.search(n, at + len(mm.group(0)))
            clause = n[at:nxt.start() if nxt else len(n)]
            live = set(bound)  # a top-level WITH between the subquery and this MATCH ends the scope of what it drops
            for w in re.finditer(r"\bWITH\b(.*?)(?=\b(?:OPTIONAL\s+MATCH|MATCH|WITH|RETURN|UNWIND|CALL|ORDER\s+BY|WHERE)\b|$)",
                                 n[sub.end():at], re.I):
                if n[:sub.end() + w.start()].count("{") != n[:sub.end() + w.start()].count("}"):
                    continue
                items = w.group(1).replace("DISTINCT", " ")
                live &= {x.strip() for x in items.split(",") if re.fullmatch(r"\s*\w+\s*", x)}
            hit = sorted(v for v in live if re.search(rf"\(\s*{re.escape(v)}\s*[):]", clause))
            if hit:
                raise TemplateLintError(f"{tid}: a MATCH after a CALL subquery re-uses {', '.join(hit)} bound before it "
                                        "(engine bug #19 matches every node instead); MATCH first, then the subqueries")
    # FalkorDB 6.0.2: right after a MATCH, a node's inline map reading a variable's property ((a {id: p.src})) is silently
    # empty without an index and fails with an index (docs/upstream/18); use WHERE, or put a WITH between the clauses
    if inline_map_after_match(n):
        raise TemplateLintError(f"{tid}: an inline property map reads a variable right after a MATCH (engine bug "
                                "#18: empty or an error); use WHERE or a WITH between the clauses")
    for col in seen:
        if re.search(rf"\$\w+\s+AS\s+{re.escape(col)}\b", m_code, re.I):
            raise TemplateLintError(f"{tid}: seen column {col!r} echoes a parameter")
    return code, limit


def parse(path: Path) -> Template:
    meta: dict[str, str] = {}
    body_lines: list[str] = []
    for line in path.read_text().splitlines():
        h = _HEADER.match(line.strip())
        if h and not body_lines:
            meta[h.group(1).lower()] = h.group(2)
            continue
        body_lines.append(line)
    tid = meta.get("id")
    if not tid:
        raise TemplateLintError(f"{path.name}: missing `// id:` header")
    # a quote in a full-line comment opens a "string" for the masker and silently swallows the code up to the next
    # quote (found building Q-OBL-SLO: "component's" cut the template in half); keep comment lines quote-free
    if any(ln.strip().startswith("//") and re.search(r"['\"]", ln) for ln in body_lines):
        raise TemplateLintError(f"{tid}: quote character in a comment line (the comment stripper would mis-mask the code)")
    returns = meta.get("returns", "rows")
    seen = tuple(c.strip() for c in meta.get("seen", "").split(",") if c.strip())
    code, limit = lint(tid, "\n".join(body_lines), returns, seen)
    display = _ALGO_PH.sub(lambda m: registry.name(m.group(1)), code)
    text = _LIMIT_END.sub(f"LIMIT {limit + 1}", display)
    return Template(tid, meta.get("purpose", ""), returns, text, display, limit, path.name, seen)


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Template]:
    out: dict[str, Template] = {}
    for p in sorted(TEMPLATE_DIR.glob("*.cypher")):
        t = parse(p)
        if t.id in out:
            raise TemplateLintError(f"duplicate template id {t.id} ({p.name}, {out[t.id].path})")
        out[t.id] = t
    return out


def load(tid: str) -> Template:
    try:
        return catalogue()[tid]
    except KeyError as e:
        raise UnknownTemplate(tid) from e
