"""Offline generator: embed globex's seeded history (incidents, postmortems, runbooks) once and commit the vectors
(data/gen/embeddings/globex_*.json). Same model and text shapes as acme's data/gen/embed.py (one vector space);
`make seed TENANT=globex` loads them onto nodes with vecf32(), so no model is needed at seed time.

    PYTHONPATH=backend .venv/bin/python data/gen/embed_globex.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from faultline.ingest.globex import docs, history  # noqa: E402
from faultline.memory.embed import MODEL, embed, incident_text  # noqa: E402

OUT = ROOT / "data" / "gen" / "embeddings"


def texts() -> dict[str, list[tuple[str, str]]]:
    hb, db = history.build(), docs.build()
    pm = {r["id"]: r for r in hb.nodes["Postmortem"]}
    pm_by_inc = {e["dst"]: pm[e["src"]] for (rel, _, _), rows in hb.edges.items() if rel == "DOCUMENTS" for e in rows}
    sym_by_inc: dict[str, list[str]] = {}
    for (rel, _, _), rows in hb.edges.items():
        if rel == "HAS_SYMPTOM":
            for e in rows:
                sym_by_inc.setdefault(e["src"], []).append(e["dst"].removeprefix("sym-").replace("-", " ", 1))
    incidents = sorted(hb.nodes["Incident"], key=lambda r: r["id"])
    return {
        "Incident": [(r["id"], incident_text(r["title"], sym_by_inc.get(r["id"], []),
                                             [pm_by_inc[r["id"]]["summary"]] if r["id"] in pm_by_inc else None))
                     for r in incidents],
        "Postmortem": [(r["id"], r["summary"]) for r in sorted(hb.nodes["Postmortem"], key=lambda r: r["id"])],
        "Runbook": [(r["id"], f"{r['title']}. {r.get('body', '')}") for r in sorted(db.nodes["Runbook"], key=lambda r: r["id"])],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for label, items in texts().items():
        vecs = embed([t for _, t in items])
        (OUT / f"globex_{label.lower()}.json").write_text(json.dumps(
            {"model": MODEL, "label": label, "tenant": "globex",
             "items": [{"id": i, "text": t, "embedding": v} for (i, t), v in zip(items, vecs)]},
            separators=(",", ":")))
        print(f"globex {label}: {len(items)} vectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
