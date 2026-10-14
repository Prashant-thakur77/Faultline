"""globex knowledge corpus (`data/gen/docs/globex/*.md`: ADRs with a SUPERSEDES chain, runbooks) → Bundle.

Same front-matter contract and node/edge shapes as acme (`ingest/docs.py` parses both); components are checked
against the globex topology, and runbook symptoms must be ids the globex history creates.
"""

from __future__ import annotations

from .. import docs as acme_docs
from ..bundle import Bundle
from . import DOCS_DIR, TENANT, topology


def build(seed: int = 42) -> Bundle:
    return acme_docs.build(seed, docs_dir=DOCS_DIR, tenant=TENANT, components=topology.generate(seed).components())
