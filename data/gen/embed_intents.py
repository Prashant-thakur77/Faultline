"""Offline generator: embed the company-brain intent exemplars (data/brain/intent_exemplars.yaml) once and commit the
vectors (data/gen/embeddings/intent_exemplar.json). Same local model as every other vector in the graph
(memory/embed.py), so a question embedded at ask time lands in the same space. `make seed` loads them onto
(:IntentExemplar) nodes with vecf32(); no model is needed at seed time. Re-run after editing the YAML (the ingest
refuses a stale file).

    PYTHONPATH=backend uv run python data/gen/embed_intents.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from faultline.ingest.brain_intents import EMBEDDINGS, exemplars  # noqa: E402
from faultline.memory.embed import MODEL, embed  # noqa: E402


def main() -> int:
    items = exemplars()
    old = {}
    if EMBEDDINGS.exists():  # keep committed vectors for unchanged texts (stable across regenerations)
        doc = json.loads(EMBEDDINGS.read_text())
        if doc.get("model") == MODEL:
            old = {x["text"]: x["embedding"] for x in doc["items"]}
    new = sorted({x["text"] for x in items if x["text"] not in old})
    fresh = dict(zip(new, embed(new))) if new else {}
    out = [{"id": x["id"], "intent": x["intent"], "text": x["text"], "embedding": old.get(x["text"]) or fresh[x["text"]]}
           for x in items]
    EMBEDDINGS.parent.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS.write_text(json.dumps({"model": MODEL, "label": "IntentExemplar", "items": out}, separators=(",", ":")))
    print(f"intent exemplars: {len(out)} vectors ({len(new)} newly embedded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
