"""ChangeFacts from a PR's changed files (pydantic-validated), deterministic, no model:
* structured config files (JSON/YAML): the before/after documents are flattened and every changed or removed key
  becomes a fact `<component>.<dotted.key> = <new value>`;
* code and properties files (Python, JS/TS, Go, Java/Kotlin, .properties/.env/.ini/.toml): every top-level constant
  assigned a LITERAL (number, boolean, quoted string) is compared before/after, and a changed one becomes a fact. Its
  key comes from the graph's own vocabulary: when the constant's name, normalised (lower case, letters and digits
  only), equals a rule key some decision sets on that component (Q-DEC-KEYS), the fact takes that exact key, so
  `const POOL_SIZE_MAX = 80` in a component's code asserts `<component>.pool.size_max = 80` when a decision on it sets
  that key, and the decision check (Q-DEC-1) sees it exactly as it would a config edit. Other constants keep
  `<component>.<name>`. A computed
  value (`2 * 1000`) is not a literal and is never guessed."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

CONFIG_SUFFIXES = (".json", ".yaml", ".yml")
CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".java", ".kt", ".properties", ".env", ".ini", ".toml")
MAX_CODE_FACTS = 200   # per file: a generated file full of constants is not a reviewable change


class ChangedFile(BaseModel):
    path: str = Field(..., min_length=1, max_length=300)
    before: str | None = Field(None, max_length=200_000)
    after: str | None = Field(None, max_length=200_000)

    @field_validator("path")
    @classmethod
    def _rel(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError("path must be repo-relative")
        return v


class ChangeFact(BaseModel):
    key: str = Field(..., pattern=r"^[A-Za-z0-9_.-]{1,200}$")
    value: str | int | float | bool | None
    about: str = Field(..., min_length=1, max_length=160)
    file: str


# Hostile input bounds (the public preflight is anonymous): a YAML alias bomb of ~300 bytes expands to GBs once
# flattened, so aliases are refused outright and the parsed document is bounded (review round 4, B2).
MAX_YAML_EVENTS = 20_000
MAX_DEPTH = 32
MAX_KEYS = 5_000
MAX_VALUE_CHARS = 10_000


def _load(path: str, text: str | None) -> Any:
    if text is None:
        return None
    if path.endswith(".json"):
        return json.loads(text)
    n = 0
    for ev in yaml.parse(text, Loader=yaml.SafeLoader):  # streaming: linear in the text, nothing expanded yet
        n += 1
        if isinstance(ev, yaml.AliasEvent):
            raise ValueError("YAML aliases are not accepted in preflight configs")
        if n > MAX_YAML_EVENTS:
            raise ValueError(f"YAML document too large (> {MAX_YAML_EVENTS} events)")
    return yaml.safe_load(text)


def flatten(doc: Any, prefix: str = "", depth: int = 0, _out: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {} if _out is None else _out
    if depth > MAX_DEPTH:
        raise ValueError(f"config nested deeper than {MAX_DEPTH} levels")
    if isinstance(doc, dict):
        for k, v in doc.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), depth + 1, out)
    elif isinstance(doc, list):
        val = json.dumps(doc, sort_keys=True)
        if len(val) > MAX_VALUE_CHARS:
            raise ValueError(f"config list value larger than {MAX_VALUE_CHARS} characters")
        out[prefix] = val
    else:
        out[prefix] = doc
    if len(out) > MAX_KEYS:
        raise ValueError(f"config has more than {MAX_KEYS} keys")
    return out


# One assignment per line: optional keywords/type words, a name, an optional type annotation, `=` (or `:=`), a
# literal, an optional `;`/`,` and an optional trailing comment. Anything else (calls, keyword arguments, expressions,
# comparisons) does not match.
_LITERAL = r"(?P<val>-?\d+(?:\.\d+)?|true|false|True|False|\"[^\"\n]{0,200}\"|'[^'\n]{0,200}')"
_ASSIGN = re.compile(r"^\s*(?:(?:export|public|private|protected|internal|static|final|const|let|var|val|"
                     r"readonly)\s+)*(?:[A-Za-z_][\w.<>\[\]]*\s+)?(?P<name>[A-Za-z_][\w.-]{0,80})\s*"
                     r"(?::\s*[\w.<>\[\]| ]{1,40})?\s*(?::=|=)\s*" + _LITERAL + r"\s*[;,]?\s*(?:(?://|#).*)?$")
_RESERVED = frozenset({"if", "for", "while", "return", "elif", "else", "case", "when"})


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _literal(v: str) -> str | int | float | bool:
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v[:1] in "\"'":
        return v[1:-1]
    return float(v) if "." in v else int(v)


def constants(text: str | None) -> dict[str, str | int | float | bool]:
    """The literal constants a code/properties file assigns at line level (last assignment wins)."""
    out: dict[str, str | int | float | bool] = {}
    for line in (text or "").splitlines()[:20_000]:
        m = _ASSIGN.match(line)
        if m and m.group("name") not in _RESERVED:
            out[m.group("name")] = _literal(m.group("val"))
    return out


def _code_key(comp: str, name: str, rule_keys: list[str]) -> str:
    """The rule key this constant sets when its normalised name matches one (with or without the key's first
    segment), else `<component>.<name>`."""
    n = _norm(name)
    for k in sorted(rule_keys):
        if n and (n == _norm(k) or n == _norm(k.split(".", 1)[1] if "." in k else k)):
            return k
    return f"{comp}.{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}"


def extract(files: list[ChangedFile], component_of: dict[str, str],
            rule_keys: dict[str, list[str]] | None = None) -> tuple[list[ChangeFact], list[str]]:
    """→ (facts, notes). `component_of` maps file path → component id (from the graph, Q-PRE-3); `rule_keys` maps a
    component → the rule keys decisions set on it (Q-DEC-KEYS), the names a code constant is matched against."""
    facts: list[ChangeFact] = []
    notes: list[str] = []
    for f in files:
        comp = component_of.get(f.path)
        if f.path.endswith(CODE_SUFFIXES) and (f.before is not None or f.after is not None):
            if comp is None:
                notes.append(f"{f.path}: code file not mapped to a component in the graph")
                continue
            before, after = constants(f.before), constants(f.after)
            changed = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)][:MAX_CODE_FACTS]
            for k in changed:
                facts.append(ChangeFact(key=_code_key(comp, k, (rule_keys or {}).get(comp, [])), value=after.get(k),
                                        about=comp, file=f"file:{f.path}"))
            if changed:
                notes.append(f"{f.path}: {len(changed)} literal constant(s) changed in code (computed values are not read)")
            continue
        if not f.path.endswith(CONFIG_SUFFIXES):
            continue
        if comp is None:
            notes.append(f"{f.path}: config file not mapped to a component in the graph")
            continue
        try:
            before, after = flatten(_load(f.path, f.before) or {}), flatten(_load(f.path, f.after) or {})
        except (ValueError, RecursionError, yaml.YAMLError) as e:
            notes.append(f"{f.path}: unparseable config ({type(e).__name__}); facts unknown")
            continue
        for k in sorted(set(before) | set(after)):
            if before.get(k) != after.get(k):
                v = after.get(k)
                facts.append(ChangeFact(key=f"{comp}.{k}", value=v if not isinstance(v, (dict, list)) else json.dumps(v),
                                        about=comp, file=f"file:{f.path}"))
    return facts, notes
