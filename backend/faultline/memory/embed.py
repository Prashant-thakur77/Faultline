"""Local 384-dim text embeddings (BAAI/bge-small-en-v1.5 via fastembed ONNX; no API key).

This only COMPUTES a vector; every similarity search runs in FalkorDB's vector index (db.idx.vector.queryNodes).
The model is cached under <repo>/.cache/fastembed (populated by `make setup`); seeded vectors are committed
(data/gen/embeddings/*.json) so seeding and judge-check need no model download.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import REPO_ROOT

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
CACHE = REPO_ROOT / ".cache" / "fastembed"


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL, cache_dir=str(CACHE))


def embed(texts: list[str]) -> list[list[float]]:
    return [[round(float(x), 6) for x in v] for v in _model().embed(list(texts))]


PRECOMPUTED = REPO_ROOT / "data" / "gen" / "embeddings" / "scenario_incident.json"


@lru_cache(maxsize=1)
def _precomputed() -> dict[str, list[float]]:
    import json

    if not PRECOMPUTED.exists():
        return {}
    d = json.loads(PRECOMPUTED.read_text())
    if d.get("model") != MODEL:
        raise RuntimeError(f"{PRECOMPUTED}: model {d.get('model')!r} != {MODEL!r}; regenerate with data/gen/embed.py")
    return {x["text"]: x["embedding"] for x in d["items"]}


def embed_one(text: str) -> list[float]:
    """Precomputed vector for a known scenario text (keyless, offline judge path), else the local model."""
    v = _precomputed().get(text)
    return list(v) if v is not None else embed([text])[0]


def incident_text(title: str, symptoms: list[str], changes: list[str] | None = None) -> str:
    """The text an incident is embedded from (same shape for past and current incidents)."""
    parts = [title.strip()]
    if symptoms:
        parts.append("Symptoms: " + ", ".join(symptoms))
    if changes:
        parts.append("Changes: " + "; ".join(changes))
    return ". ".join(parts)
