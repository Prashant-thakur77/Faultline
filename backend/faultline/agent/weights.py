"""Load `weights.yaml` (deterministic scoring and gate parameters; numbers come from code, never the LLM)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

WEIGHTS_PATH = Path(__file__).with_name("weights.yaml")


@lru_cache(maxsize=1)
def weights() -> dict[str, Any]:
    return yaml.safe_load(WEIGHTS_PATH.read_text())


def tier_weight(tier: int | None) -> float:
    tw = weights()["impact"]["tier_weight"]
    return float(tw.get(int(tier or 3), tw[3]))


def tier_weights_param() -> list[float]:
    """The tier weights as the `$tw` list the in-engine scoring takes (index 0 = tier 1; faultline.tierWeight)."""
    tw = weights()["impact"]["tier_weight"]
    return [float(tw.get(t, tw[3])) for t in range(1, max(int(k) for k in tw) + 1)]
