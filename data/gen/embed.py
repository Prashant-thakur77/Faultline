"""Offline generator: embed the seeded history (incidents, postmortems, runbooks) once and commit the vectors
(data/gen/embeddings/*.json). `make seed` loads them onto nodes with vecf32(); no model is needed at seed time.

    PYTHONPATH=backend uv run python data/gen/embed.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from faultline.ingest import docs, history  # noqa: E402
from faultline.memory.embed import MODEL, embed, incident_text  # noqa: E402

OUT = ROOT / "data" / "gen" / "embeddings"
BENCH_REPORT = "{target} errors are elevated"  # evals/gate_bench.py uses the same wording (a unit test checks it)


def main() -> int:
    if "--scenarios-only" not in sys.argv:
        history_vectors()
    return scenario_vectors()


def history_vectors() -> None:
    hb, db = history.build(), docs.build()
    pm_by_inc = {e["dst"]: next(r for r in hb.nodes["Postmortem"] if r["id"] == e["src"])
                 for (rel, _, _), rows in hb.edges.items() if rel == "DOCUMENTS" for e in rows}
    sym_by_inc: dict[str, list[str]] = {}
    for (rel, _, _), rows in hb.edges.items():
        if rel == "HAS_SYMPTOM":
            for e in rows:
                sym_by_inc.setdefault(e["src"], []).append(e["dst"].removeprefix("sym-").replace("-", " ", 1))
    incidents = sorted(hb.nodes["Incident"], key=lambda r: r["id"])
    texts = {"Incident": [(r["id"], incident_text(r["title"], sym_by_inc.get(r["id"], []),
                                                  [pm_by_inc[r["id"]]["summary"]] if r["id"] in pm_by_inc else None))
                          for r in incidents],
             "Postmortem": [(r["id"], r["summary"]) for r in sorted(hb.nodes["Postmortem"], key=lambda r: r["id"])],
             "Runbook": [(r["id"], f"{r['title']}. {r.get('body', '')}") for r in sorted(db.nodes["Runbook"], key=lambda r: r["id"])]}
    OUT.mkdir(parents=True, exist_ok=True)
    for label, items in texts.items():
        vecs = embed([t for _, t in items])
        (OUT / f"{label.lower()}.json").write_text(json.dumps(
            {"model": MODEL, "label": label, "items": [{"id": i, "text": t, "embedding": v} for (i, t), v in zip(items, vecs)]},
            separators=(",", ":")))
        print(f"{label}: {len(items)} vectors")


def scenario_vectors() -> int:
    # scenario intake texts (the same text scenario.prepare embeds), so the keyless judge path needs no model
    import yaml

    from faultline.memory.embed import PRECOMPUTED

    scen = yaml.safe_load((ROOT / "data" / "scenarios" / "scenarios.yaml").read_text())
    items = []
    for s in scen.get("scenarios", scen) if isinstance(scen, dict) else scen:
        tgts = sorted({a["target"] for a in s.get("alerts", [])})
        syms = [f"{next(a['metric'] for a in s['alerts'] if a['target'] == t)} {t}" for t in tgts]
        items.append(incident_text(s.get("report") or s.get("name", s["id"]), syms))
    # product-check probes that open an incident outside scenarios.yaml (evals/globex_checks.py S8)
    items.append(incident_text("Recommendation rail is timing out", ["latency recommender"]))
    # gate bench intake (evals/gate_bench.py): one alert on any acme service/datastore, BENCH_REPORT wording
    topo = yaml.safe_load((ROOT / "data" / "topology" / "otel-demo.yaml").read_text())
    for c in sorted([x["id"] for x in topo["services"]] + [x["id"] for x in topo["datastores"]]):
        items.append(incident_text(BENCH_REPORT.format(target=c), [f"error_rate {c}"]))
    # keep committed vectors for texts that did not change (stable across regenerations); embed only new texts
    old = {x["text"]: x["embedding"] for x in json.loads(PRECOMPUTED.read_text())["items"]} if PRECOMPUTED.exists() else {}
    new = [t for t in items if t not in old]
    fresh = dict(zip(new, embed(new))) if new else {}
    vecs = [old.get(t) or fresh[t] for t in items]
    PRECOMPUTED.write_text(json.dumps({"model": MODEL, "items": [{"text": t, "embedding": v} for t, v in zip(items, vecs)]},
                                      separators=(",", ":")))
    print(f"scenario intake: {len(items)} vectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
