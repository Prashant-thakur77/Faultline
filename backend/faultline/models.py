"""Structured domain models for the incident workflow.

These mirror frontend/src/lib/types.ts exactly — change both together.
The investigation engine distinguishes facts (EvidenceItem, machine-produced),
hypotheses (LLM-proposed, must be resolved by evidence), and actions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class IncidentStage(str, Enum):
    REPORTED = "REPORTED"
    CONTEXT_DISCOVERY = "CONTEXT_DISCOVERY"
    LINEAGE_TRAVERSAL = "LINEAGE_TRAVERSAL"
    HYPOTHESIS_GENERATION = "HYPOTHESIS_GENERATION"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    ROOT_CAUSE_CONFIRMED = "ROOT_CAUSE_CONFIRMED"
    REPAIR_GENERATED = "REPAIR_GENERATED"
    REPAIR_TESTING = "REPAIR_TESTING"
    VERIFIED = "VERIFIED"
    WRITEBACK_COMPLETE = "WRITEBACK_COMPLETE"
    NO_INCIDENT = "NO_INCIDENT"
    FAILED = "FAILED"


# Stages may only move forward along this order (NO_INCIDENT / FAILED are terminal exits).
STAGE_ORDER: list[IncidentStage] = [
    IncidentStage.REPORTED,
    IncidentStage.CONTEXT_DISCOVERY,
    IncidentStage.LINEAGE_TRAVERSAL,
    IncidentStage.HYPOTHESIS_GENERATION,
    IncidentStage.EVIDENCE_COLLECTION,
    IncidentStage.ROOT_CAUSE_CONFIRMED,
    IncidentStage.REPAIR_GENERATED,
    IncidentStage.REPAIR_TESTING,
    IncidentStage.VERIFIED,
    IncidentStage.WRITEBACK_COMPLETE,
]

NodeStatus = Literal["healthy", "investigating", "suspicious", "affected", "root_cause", "repaired"]
EvidenceKind = Literal[
    "metadata", "profile", "baseline_comparison", "sql", "lineage", "test", "patch", "writeback"
]
EvidenceSource = Literal["falkordb", "warehouse", "pipeline", "git", "agent"]
HypothesisStatus = Literal["proposed", "investigating", "eliminated", "confirmed"]
PatchStatus = Literal["proposed", "applied", "testing", "verified", "rejected"]


class ColumnMapping(BaseModel):
    upstream: str
    downstream: str


class LineageNode(BaseModel):
    urn: str
    name: str
    platform: str
    layer: Literal["source", "staging", "marts", "metric"]
    status: NodeStatus = "healthy"


class LineageEdge(BaseModel):
    source: str  # upstream urn
    target: str  # downstream urn
    columns: list[ColumnMapping] | None = None


class DailyPoint(BaseModel):
    day: str
    revenue_usd: float
    baseline: float | None = None


class MetricSnapshot(BaseModel):
    kpi_day: str
    revenue: float
    expected_revenue: float
    anomaly_ratio: float
    status: Literal["ok", "anomalous"]
    daily: list[DailyPoint] = Field(default_factory=list)


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    description: str
    target_urn: str
    status: HypothesisStatus = "proposed"
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """A fact. Always produced by deterministic tool code, never free-typed by the LLM."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    ts: str = Field(default_factory=now_iso)
    kind: EvidenceKind
    title: str
    detail: str
    data: Any = None
    source: EvidenceSource
    # Which concrete transport produced this fact (e.g. "GRAPH.RO_QUERY", "duckdb", "pytest", "git").
    transport: str | None = None


class ProposedPatch(BaseModel):
    file: str
    diff: str
    reasoning: str
    status: PatchStatus = "proposed"


class TestFailure(BaseModel):
    name: str
    message: str


class TestReport(BaseModel):
    total: int
    passed: int
    failed: int
    failures: list[TestFailure] = Field(default_factory=list)


class RootCause(BaseModel):
    summary: str
    asset_urn: str
    field: str
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class Writeback(BaseModel):
    incident_urn: str | None = None
    status: str = "pending"
    detail: str = ""


class GitArtifact(BaseModel):
    branch: str
    commit: str
    diff_stat: str
    pr_url: str | None = None


class IncidentState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inc"))
    report_text: str
    stage: IncidentStage = IncidentStage.REPORTED
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    patch: ProposedPatch | None = None
    tests_before: TestReport | None = None
    tests_after: TestReport | None = None
    metric_before: MetricSnapshot | None = None
    metric_after: MetricSnapshot | None = None
    root_cause: RootCause | None = None
    writeback: Writeback | None = None
    git_artifact: GitArtifact | None = None
    final_summary: str | None = None
    error: str | None = None

    # -- helpers -------------------------------------------------------------

    def evidence_by_id(self, eid: str) -> EvidenceItem | None:
        return next((e for e in self.evidence if e.id == eid), None)

    def node(self, urn: str) -> LineageNode | None:
        return next((n for n in self.nodes if n.urn == urn), None)

    def can_advance_to(self, target: IncidentStage) -> bool:
        if target in (IncidentStage.NO_INCIDENT, IncidentStage.FAILED):
            return True
        if self.stage in (IncidentStage.NO_INCIDENT, IncidentStage.FAILED):
            return False
        try:
            return STAGE_ORDER.index(target) > STAGE_ORDER.index(self.stage)
        except ValueError:
            return False
