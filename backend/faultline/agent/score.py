"""Deterministic suspect scoring. Numbers come from code + weights.yaml, never the LLM.

score(c) = w_path·1/(1+hops) + w_time·exp(−|onset − at|/τ) + w_anom·anomaly_term + w_rank·pagerank_norm
         + w_flow·flow_share + w_prior·family_prior
Terms that are not yet measured contribute 0 and are reported as such (legible, not asserted).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .weights import weights


@dataclass
class Score:
    id: str
    total: float
    path: float
    time: float
    anomaly: float
    rank: float
    flow: float
    prior: float
    hops: int | None
    minutes_before_onset: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def score(*, cause_id: str, hops: int | None, at_ms: int | None, onset_ms: int, anomaly_ratio: float | None = None,
          band: float | None = None, pagerank_norm: float = 0.0, flow_share: float | None = None,
          family_prior: float = 0.0) -> Score:
    w = weights()["score"]
    path = 1.0 / (1 + hops) if hops is not None else 0.0
    mins = (onset_ms - at_ms) / 60_000 if at_ms is not None else None
    time = math.exp(-abs(mins) / float(w["tau_min"])) if mins is not None and mins >= 0 else 0.0
    anom = 0.0
    if anomaly_ratio and band and band > 1:
        anom = min(1.0, abs(math.log(anomaly_ratio)) / math.log(band))
    flow = float(flow_share) if flow_share is not None else 0.0
    parts = {
        "path": w["w_path"] * path, "time": w["w_time"] * time, "anomaly": w["w_anom"] * anom,
        "rank": w["w_rank"] * float(pagerank_norm), "flow": w["w_flow"] * flow, "prior": w["w_prior"] * float(family_prior),
    }
    return Score(cause_id, round(sum(parts.values()), 4), *(round(v, 4) for v in parts.values()), hops,
                 round(mins, 2) if mins is not None else None)


def rank(scores: list[Score]) -> list[Score]:
    return sorted(scores, key=lambda s: (-s.total, s.id))
