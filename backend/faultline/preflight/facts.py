"""ChangeFacts from a PR's changed files (pydantic-validated). Deterministic extractor: for structured config files
(JSON/YAML) the before/after documents are flattened and every changed or removed key becomes a fact
`<component>.<dotted.key> = <new value>`. Code diffs need the LLM extractor (live mode); keyless runs say so."""

from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

CONFIG_SUFFIXES = (".json", ".yaml", ".yml")


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


def extract(files: list[ChangedFile], component_of: dict[str, str]) -> tuple[list[ChangeFact], list[str]]:
    """→ (facts, notes). `component_of` maps file path → component id (from the graph, Q-PRE-3)."""
    facts: list[ChangeFact] = []
    notes: list[str] = []
    for f in files:
        comp = component_of.get(f.path)
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
