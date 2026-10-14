"""Cross-domain links (service → raw table) → Bundle."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..agent.weights import weights
from .bundle import Bundle
from .lineage_to_graph import flow

CROSS = Path(__file__).resolve().parents[3] / "data" / "topology" / "cross_domain.yaml"


def build(path: Path = CROSS) -> Bundle:
    spec = yaml.safe_load(path.read_text())
    b = Bundle()
    data_tier = weights()["impact"]["data_tier_weight"]
    for e in spec["emits"]:
        b.edge("EMITS", "Service", e["service"], "Table", e["table"], cap=e["cap"], why=e["why"])
        flow(b, "Service", e["service"], "Table", e["table"], e["cap"], e["cap"] * data_tier, "cross", cap_why=e["why"])
    return b
