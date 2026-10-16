"""Company-brain intent exemplars → (:IntentExemplar {id, intent, text, refuse, embedding}) in every golden graph.

The brain routes a question with one read-only template (Q-BRAIN-INTENT): the question's nearest exemplars by
meaning (the IntentExemplar vector index) fused with its full-text matches (the IntentExemplar full-text index), in
the engine. These nodes are that router's only knowledge; nothing about routing lives in Python.

Sources: data/brain/intent_exemplars.yaml (texts, written from each intent's definition; see the header there) and
data/gen/embeddings/intent_exemplar.json (their vectors, generated once by data/gen/embed_intents.py). The seeder
writes the vectors with vecf32(). A YAML text with no committed vector fails loudly (regenerate), never seeds a node
the vector index cannot see.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ..memory.embed import MODEL
from .bundle import Bundle

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "data" / "brain" / "intent_exemplars.yaml"
EMBEDDINGS = ROOT / "data" / "gen" / "embeddings" / "intent_exemplar.json"


def exemplars() -> list[dict]:
    """Every exemplar in the YAML, with a stable id (a hash of intent and text, so reordering changes nothing)."""
    doc = yaml.safe_load(SOURCE.read_text())
    out, ids = [], set()
    for intent, spec in (doc.get("intents") or {}).items():
        texts = spec.get("exemplars") or []
        if not texts:
            raise ValueError(f"{SOURCE}: intent {intent!r} has no exemplars")
        for text in texts:
            text = " ".join(str(text).split())
            xid = "ix-" + hashlib.sha256(f"{intent}|{text}".encode()).hexdigest()[:12]
            if xid in ids:
                raise ValueError(f"{SOURCE}: duplicate exemplar {text!r} under {intent!r}")
            ids.add(xid)
            out.append({"id": xid, "intent": intent, "text": text, "refuse": bool(spec.get("refuse", False))})
    return out


def build() -> Bundle:
    if not EMBEDDINGS.exists():
        raise FileNotFoundError(f"{EMBEDDINGS} missing: run `PYTHONPATH=backend uv run python data/gen/embed_intents.py`")
    doc = json.loads(EMBEDDINGS.read_text())
    if doc.get("model") != MODEL:
        raise ValueError(f"{EMBEDDINGS}: model {doc.get('model')!r} != {MODEL!r}; regenerate")
    vec = {x["id"]: x for x in doc["items"]}
    b = Bundle()
    for x in exemplars():
        v = vec.get(x["id"])
        if v is None or v["text"] != x["text"]:
            raise ValueError(f"{EMBEDDINGS} is stale for {x['text']!r}: run data/gen/embed_intents.py")
        b.node("IntentExemplar", x["id"], intent=x["intent"], text=x["text"], refuse=x["refuse"],
               embedding=v["embedding"], embedding_model=MODEL)
    return b
