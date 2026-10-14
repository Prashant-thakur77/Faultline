"""Typed specialist contracts (pydantic v2).

A specialist returns exactly ONE `SpecialistReport` object. Anything else (prose, a code-fenced blob, a JSON object
that does not validate, a report with no evidence) is rejected with `ContractError`; the dispatcher retries once and
then records `status="insufficient"`. Validation against the run happens in code, from read-only graph queries:

* every `suspect_ids` entry was SEEN in a graph result of this run (Q-GATE-G1, the same grounding G1 uses);
* every `evidence_id` was produced by this run (Q-GATE-G1);
* every observation `field=value` appears in the recorded payload of the evidence it is attached to (Q-EV-PAYLOAD).

The model never writes an evidence id: `EvidenceRef`s are built from tool results by the tool layer (`ref`).
`RootCauseReport` / `Proven` / `Inferred` are the report models in `agent/report.py` (built from the graph), re-exported
here so the contract module names every typed object the plan lists.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..graph.ro import RO
from .report import Inferred, Proven, RootCauseReport

CONTRACT_VERSION = "1"
Role = Literal["topology", "telemetry", "data", "change", "code"]
ROLES: tuple[str, ...] = ("topology", "telemetry", "data", "change", "code")
_OBS = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*=.*$", re.S)


class ContractError(ValueError):
    """A specialist answer that is not a valid contract (prose, fences, schema or grounding failure)."""


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(..., min_length=4, max_length=40)   # created by the tool layer, never by the model
    tool: str = Field(..., min_length=1, max_length=80)
    cypher: str | None = None
    params: dict | None = None
    observations: list[str] = Field(default_factory=list)        # "field=value" strings copied from the tool result

    @model_validator(mode="after")
    def _obs_shape(self) -> "EvidenceRef":
        bad = [o for o in self.observations if not _OBS.match(o)]
        if bad:
            raise ValueError(f"observations must be 'field=value' strings: {bad[:3]}")
        return self


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["1"]
    role: Role
    incident_id: str = Field(..., min_length=1)
    status: Literal["complete", "insufficient"]
    suspect_ids: list[str] = Field(default_factory=list)  # validated ⊆ the run's seen ids
    evidence: list[EvidenceRef] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)      # what this channel looked for and could not establish
    limits: list[str] = Field(default_factory=list)        # what this channel cannot see at all (stated, not hidden)

    @model_validator(mode="after")
    def _complete_needs_evidence(self) -> "SpecialistReport":
        # §6.3: empty evidence is rejected. An `insufficient` report may carry none (its tools all failed); it then
        # names nothing, so it can never support a claim.
        if self.status == "complete" and not self.evidence:
            raise ValueError("a complete report needs at least one evidence item")
        if self.status == "insufficient" and self.suspect_ids and not self.evidence:
            raise ValueError("an insufficient report without evidence cannot name suspects")
        return self


def obs(field: str, value: Any) -> str:
    """One observation string in the canonical form the validator re-derives from payloads."""
    return f"{field}={_fmt(value)}"


def _fmt(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, default=str)


def flatten(payload: Any, out: set[str] | None = None) -> set[str]:
    """Every `field=value` pair inside a payload (scalars, and each element of a list of scalars)."""
    out = set() if out is None else out
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, (dict,)):
                flatten(v, out)
            elif isinstance(v, list):
                if all(not isinstance(x, (dict, list)) for x in v):
                    out.add(f"{k}={_fmt(v)}")
                    out.update(f"{k}={_fmt(x)}" for x in v)
                else:
                    for x in v:
                        flatten(x, out)
            else:
                out.add(f"{k}={_fmt(v)}")
    elif isinstance(payload, list):
        for x in payload:
            flatten(x, out)
    return out


def ref(result: dict, tool: str, params: dict, observations: list[str] | None = None) -> EvidenceRef | None:
    """EvidenceRef from a tool result (graph tools carry their Cypher; external tools carry their params)."""
    ev = result.get("evidence_id") if isinstance(result, dict) else None
    if not ev:
        return None
    return EvidenceRef(evidence_id=ev, tool=tool, cypher=result.get("cypher"), params=result.get("params") or params,
                       observations=observations or [])


def parse_report(raw: Any, *, role: str, incident_id: str) -> SpecialistReport:
    """Accept exactly one contract object. Prose, code fences, lists, extra keys or a role/incident mismatch → ContractError."""
    if isinstance(raw, SpecialistReport):
        data: Any = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    elif isinstance(raw, (str, bytes)):
        text = raw.decode() if isinstance(raw, bytes) else raw
        t = text.strip()
        if "```" in t:
            raise ContractError("code fences are not a contract: return exactly one JSON object")
        if not (t.startswith("{") and t.endswith("}")):
            raise ContractError("free prose is not a contract: return exactly one JSON object")
        try:
            data = json.loads(t)
        except json.JSONDecodeError as e:
            raise ContractError(f"not one JSON object: {e.msg}") from e
    else:
        raise ContractError(f"a specialist must return a contract object, not {type(raw).__name__}")
    if not isinstance(data, dict):
        raise ContractError("a contract is one JSON object")
    try:
        rep = SpecialistReport.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        raise ContractError(f"contract invalid at {'.'.join(str(x) for x in first['loc']) or '(root)'}: {first['msg']}") from e
    if rep.role != role:
        raise ContractError(f"role mismatch: dispatched {role}, report says {rep.role}")
    if rep.incident_id != incident_id:
        raise ContractError(f"incident mismatch: {rep.incident_id} != {incident_id}")
    return rep


def validate_against_run(rep: SpecialistReport, ro: RO, run_id: str) -> SpecialistReport:
    """Grounding in code, from read-only queries: suspects seen, evidence produced by this run, observations present."""
    ev_ids = sorted({e.evidence_id for e in rep.evidence})
    g1 = ro.run("Q-GATE-G1", {"run": run_id, "ids": sorted(set(rep.suspect_ids)), "evidence": ev_ids}).rows[0]
    unseen = sorted(set(rep.suspect_ids) - set(g1["seen"]))
    if unseen:
        raise ContractError(f"suspect ids not seen in a graph result of this run: {unseen}")
    unknown = sorted(set(ev_ids) - set(g1["evidence"]))
    if unknown:
        raise ContractError(f"evidence ids not produced by this run: {unknown}")
    if any(e.observations for e in rep.evidence):
        payloads = {r["id"]: r["payload"] for r in ro.run("Q-EV-PAYLOAD", {"run": run_id, "ids": ev_ids}).rows}
        for e in rep.evidence:
            if not e.observations:
                continue
            raw = payloads.get(e.evidence_id) or ""
            try:
                have = flatten(json.loads(raw))
            except (TypeError, json.JSONDecodeError):  # truncated payload: fall back to raw containment
                have = set()
            missing = [o for o in e.observations if o not in have and _raw_pair(o) not in raw]
            if missing:
                raise ContractError(f"observations not in the payload of {e.evidence_id}: {missing[:3]}")
    return rep


def _raw_pair(o: str) -> str:
    k, v = o.split("=", 1)
    return f'"{k}": {v}' if not _is_string_value(v) else f'"{k}": "{v}"'


def _is_string_value(v: str) -> bool:
    try:
        json.loads(v)
        return False
    except json.JSONDecodeError:
        return True


def insufficient(role: str, incident_id: str, why: str, limits: list[str] | None = None) -> SpecialistReport:
    """The recorded outcome after a rejected answer and its one retry (or when a role has nothing to examine)."""
    return SpecialistReport(contract_version="1", role=role, incident_id=incident_id, status="insufficient",  # type: ignore[arg-type]
                            suspect_ids=[], evidence=[], unknowns=[why[:300]], limits=limits or [])


__all__ = ["CONTRACT_VERSION", "ROLES", "ContractError", "EvidenceRef", "SpecialistReport", "RootCauseReport", "Proven",
           "Inferred", "obs", "flatten", "ref", "parse_report", "validate_against_run", "insufficient"]
