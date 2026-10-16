"""Structured domain models for the incident workflow.

The warehouse repair path's records: the proposed transform patch and the invariant suite's reports and metric
snapshots. Everything the agent knows or decides lives in FalkorDB, not here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PatchStatus = Literal["proposed", "applied", "testing", "verified", "rejected"]


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


