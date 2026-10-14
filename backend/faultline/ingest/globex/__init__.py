"""globex: the generated SCALE tenant (M8).

`data/topology/globex.yaml` is the declarative spec (12 domains, backbone calls, datastores, external
dependencies, flags, ownership history, eight incident archetypes). The submodules expand it with one seeded
`random.Random` stream each (seed 42), never the wall clock (times derive from `clock.ANCHOR_MS`), and never
touch FalkorDB. Each submodule is a seed producer (`build() -> Bundle`, scripts/seed.py PRODUCERS["globex"]):

* `topology`   200 services (preferential-attachment CALLS, PROPAGATES_TO/DEPENDS_ON flow), 6 datastores,
               3 external dependencies, endpoints, feature flags with containment levers;
* `org`        12 teams, 180 people (VP → directors → leads → engineers, 10% inactive), weekly ON_CALL rota,
               COLLABORATES, OWNS + OWNED_AT (including ownership moves and two orphaned services);
* `history`    120 days of Repos/Files/Commits/PRs/Deploys and 150 past incidents in eight families;
* `docs`       ADRs (a SUPERSEDES chain) and runbooks from `data/gen/docs/globex/*.md`;
* `embeddings` committed vectors (`data/gen/embeddings/globex_*.json`, made by `data/gen/embed_globex.py`).

Same labels, relationship types and property conventions as acme, so every template runs unchanged. Ids are
globally unique across labels and never reuse an acme id (tests/ingest/test_globex.py).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..bundle import Bundle

TENANT = "globex"
REPO_ROOT = Path(__file__).resolve().parents[4]
SPEC_PATH = REPO_ROOT / "data" / "topology" / "globex.yaml"
DOCS_DIR = REPO_ROOT / "data" / "gen" / "docs" / "globex"
EMBED_DIR = REPO_ROOT / "data" / "gen" / "embeddings"


@lru_cache(maxsize=1)
def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    spec = yaml.safe_load(path.read_text())
    if spec.get("tenant") != TENANT:
        raise ValueError(f"{path}: tenant must be {TENANT!r}")
    return spec


def build(seed: int = 42) -> Bundle:
    """Everything except embeddings (convenience for tests; the seeder lists the submodules)."""
    from . import docs, history, org, topology

    b = Bundle()
    for m in (topology, org, history, docs):
        b.merge(m.build(seed))
    return b
