"""globex obligations → Bundle (same model as `ingest/obligations.py`): one error-rate SLO per tier-1/tier-2
service of the generated topology, and the synthetic customers listed in `data/topology/globex.yaml`."""

from __future__ import annotations

from ..bundle import Bundle
from ..obligations import build_from
from . import TENANT, load_spec
from .topology import generate


def build(seed: int = 42) -> Bundle:
    topo = generate(seed)
    return build_from(load_spec(), topo.services, dict(topo.label), TENANT, seed)
