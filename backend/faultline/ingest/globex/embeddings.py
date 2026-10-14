"""Committed globex embeddings (`data/gen/embeddings/globex_*.json`, generated once by
`data/gen/embed_globex.py` with the same local model as acme) → `embedding` props on the existing
Incident/Postmortem/Runbook nodes. The seeder writes them with vecf32() so the vector indexes see them."""

from __future__ import annotations

import json

from ...memory.embed import MODEL
from ..bundle import Bundle
from . import EMBED_DIR

LABELS = ("incident", "postmortem", "runbook")


def build(seed: int = 42) -> Bundle:  # noqa: ARG001 - common producer contract
    b = Bundle()
    for name in LABELS:
        path = EMBED_DIR / f"globex_{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: run `PYTHONPATH=backend python data/gen/embed_globex.py`")
        doc = json.loads(path.read_text())
        if doc.get("model") != MODEL:
            raise ValueError(f"{path}: model {doc.get('model')!r} != {MODEL!r}; regenerate")
        for it in doc["items"]:
            b.node(doc["label"], it["id"], embedding=it["embedding"], embedding_model=doc["model"])
    return b
