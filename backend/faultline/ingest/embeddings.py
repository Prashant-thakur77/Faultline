"""Committed embeddings (data/gen/embeddings/*.json, generated once by data/gen/embed.py) → vectors on the
existing Incident/Postmortem/Runbook nodes (written with vecf32() by the seeder)."""

from __future__ import annotations

import json
from pathlib import Path

from .bundle import Bundle

DIR = Path(__file__).resolve().parents[3] / "data" / "gen" / "embeddings"


def build() -> Bundle:
    b = Bundle()
    for name in ("incident", "postmortem", "runbook"):  # node vectors (scenario_incident.json is intake input)
        doc = json.loads((DIR / f"{name}.json").read_text())
        for it in doc["items"]:
            b.node(doc["label"], it["id"], embedding=it["embedding"], embedding_model=doc["model"])
    return b
