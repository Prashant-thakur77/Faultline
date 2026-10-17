"""Vector recall@10 of FalkorDB's HNSW index against an exact scan, at several efRuntime values (M20 #3).

Every vector decision starts from `db.idx.vector.queryNodes` (warm recall Q-MEM-1, the vector seeds, brain routing). The
index is approximate (HNSW); its query-time beam `efRuntime` defaults to 10. This eval measures how many of the TRUE ten
nearest neighbours (an exact `vec.cosineDistance` scan over the label, Q-VEC-EXACT) the index returns (Q-VEC-ANN), per
label and per efRuntime, on clean-room copies of the seeded goldens:

* acme and globex: the seeded Incident, Postmortem, Runbook and IntentExemplar embeddings (every stored vector is a query);
* history2k: acme's 40 incident embeddings plus 2,000 synthetic past incidents, each a noisy copy of one of them
  (Gaussian noise σ = 0.05 per dimension, then normalised; seed 42), a proxy for a long incident history where an
  approximate index can start to miss neighbours. 60 queries (the 40 real ones and 20 synthetic, fixed by the seed).

recall@10 for one query = |index hits whose distance ≤ the 10th exact distance + 1e-5| / min(10, n) (tie-aware: an equally
near neighbour counts). Reported as the mean over queries. The product's efRuntime (schema.cypher) is the smallest
measured value whose recall@10 is ≥ 0.99 on every set; `--choose` prints it.

    PYTHONPATH=backend uv run python evals/vector_recall.py      # → evals/results/vector_recall.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:
    sys.path.insert(0, str(ROOT / "backend"))

EFS = (10, 20, 50, 100, 200)
# (M, efConstruction, efRuntime) beyond the default M 16 / efConstruction 200: a denser HNSW graph, built slower
VARIANTS = ((32, 400, 100), (32, 400, 200))
LABELS = ("Incident", "Postmortem", "Runbook", "IntentExemplar")
TARGET = 0.99
SYNTH_N, SYNTH_SIGMA, SYNTH_QUERIES, SEED = 2000, 0.05, 20, 42
EPS = 1e-5


def _ids(ro, label: str) -> list[str]:
    out, after = [], ""
    while True:   # keyset paging over the label's nodes with an embedding (Q-VEC-IDS, 100 a page)
        page = ro.run("Q-VEC-IDS", {"label": label, "after": after})
        out += [r["id"] for r in page.rows]
        if not page.truncated:
            return out
        after = out[-1]


def recall_for(ro, label: str, queries: list[tuple[str, list[float]]]) -> tuple[float, float, int]:
    """(mean recall@10, p50 index query ms, n) for one label on the room `ro` reads."""
    rs, ms = [], []
    for _, q in queries:
        exact = ro.run("Q-VEC-EXACT", {"label": label, "q": q}).rows
        if not exact:
            continue
        k = len(exact)
        cut = float(exact[-1]["distance"]) + EPS
        t0 = time.perf_counter()
        ann = ro.run("Q-VEC-ANN", {"label": label, "q": q})
        ms.append((time.perf_counter() - t0) * 1000)
        hits = sum(1 for r in ann.rows if r["distance"] is not None and float(r["distance"]) <= cut)
        rs.append(min(hits, k) / k)
    return (round(statistics.fmean(rs), 4) if rs else None, round(statistics.median(ms), 3) if ms else None, len(rs))


def _vectors(ro, ids: list[str]) -> list[tuple[str, list[float]]]:
    return [(i, [float(x) for x in ro.run("Q-VEC-1", {"id": i}).rows[0]["embedding"]]) for i in ids]


def _noisy(v: list[float], rnd: random.Random) -> list[float]:
    w = [x + rnd.gauss(0.0, SYNTH_SIGMA) for x in v]
    n = math.sqrt(sum(x * x for x in w)) or 1.0
    return [x / n for x in w]


def measure(tenant: str, labels: tuple[str, ...], efs: tuple[int, ...], synth: int = 0, progress: bool = True) -> dict:
    from faultline.graph import client
    from faultline.graph import copy as gcopy
    from faultline.graph import writes
    from faultline.graph.ro import RO
    from faultline.graph.tenant import golden_graph

    db = client.engine()
    room = f"eval_{tenant}_vecrecall_{uuid.uuid4().hex[:8]}"
    out: dict = {}
    try:
        gcopy.copy_graph(db, golden_graph(tenant), room)
        g = db.select_graph(room)
        ro = RO(tenant, room)
        sets: dict[str, tuple[str, list]] = {}
        for label in labels:
            ids = _ids(ro, label)
            if len(ids) >= 2:
                sets[f"{tenant}_{label.lower()}"] = (label, _vectors(ro, ids))

        def run_sets(names: list[str]) -> None:
            for name in names:
                label, qs = sets[name]
                out[name] = {"label": label, "vectors": len(_ids(ro, label)), "queries": len(qs), "recall": {},
                             "ms_p50": {}}
                for key, m, efc, ef in [(str(e), 16, 200, e) for e in efs] + [
                        (f"m{m}_efc{efc}_ef{e}", m, efc, e) for m, efc, e in VARIANTS]:
                    t0 = time.perf_counter()
                    writes.rebuild_vector_index(g, label, ef_runtime=ef, m=m, ef_construction=efc)   # waits: OPERATIONAL
                    build_ms = round((time.perf_counter() - t0) * 1000, 1)
                    rec, ms, n = recall_for(ro, label, qs)
                    out[name]["recall"][key], out[name]["ms_p50"][key] = rec, ms
                    out[name].setdefault("build_ms", {})[key] = build_ms
                    if progress:
                        print(f"  {name} {key}: recall@10 {rec} ({n} queries, index p50 {ms} ms, build {build_ms} ms)",
                              file=sys.stderr)

        run_sets(list(sets))                     # the seeded vectors first, before any synthetic node exists
        if synth:
            label = "Incident"
            base = _vectors(ro, _ids(ro, label))
            rnd = random.Random(SEED)
            rows = []
            for j in range(synth):
                src = base[j % len(base)][1]
                rows.append({"id": f"inc-synth-{j:05d}", "title": "synthetic past incident (vector recall eval)",
                             "stage": "RESOLVED", "embedding": _noisy(src, rnd)})
            for lo in range(0, len(rows), 300):   # product writers only (clean room): nodes, then vecf32 vectors
                writes.upsert_nodes(g, label, rows[lo:lo + 300])
                writes.set_vectors(g, label, rows[lo:lo + 300])
            qs = base + [(r["id"], r["embedding"]) for r in random.Random(SEED + 1).sample(rows, SYNTH_QUERIES)]
            hist = f"history{synth // 1000}k_incident"
            sets[hist] = (label, qs)
            run_sets([hist])
    finally:
        gcopy.delete_if_exists(db, room)
    return out


def choose(sets: dict, keys: list[str], target: float = TARGET) -> str | None:
    """The first configuration (cheapest first: default graph, ascending efRuntime; then the denser graphs) whose
    recall@10 is ≥ target on every set."""
    for key in keys:
        if all((s["recall"].get(key) or 0) >= target for s in sets.values()):
            return key
    return None


def keys_in_order() -> list[str]:
    return [str(e) for e in EFS] + [f"m{m}_efc{efc}_ef{e}" for m, efc, e in VARIANTS]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "vector_recall.json"))
    ap.add_argument("--synthetic", type=int, default=SYNTH_N)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    sets: dict = {}
    sets.update(measure("acme", LABELS, EFS, synth=a.synthetic, progress=not a.quiet))
    sets.update(measure("globex", LABELS, EFS, progress=not a.quiet))
    from faultline.graph import writes

    chosen = choose(sets, keys_in_order())
    res = {"reason": "M20 #3: measure the HNSW index's recall@10 against an exact scan before setting efRuntime "
                     "(docs/API.md; the default efRuntime 10 is what every graph used before)",
           "efs": list(EFS), "variants": [list(v) for v in VARIANTS], "configs": keys_in_order(), "target": TARGET,
           "chosen": chosen, "default": "10",
           "schema": writes.schema_vector_options().get("Incident") or {},
           "synthetic": {"n": a.synthetic, "sigma": SYNTH_SIGMA, "queries": SYNTH_QUERIES, "seed": SEED},
           "sets": sets, "seconds": round(time.time() - t0, 1)}
    Path(a.out).write_text(json.dumps(res, indent=2) + "\n")
    worst = {k: min(s["recall"][k] for s in sets.values()) for k in keys_in_order()}
    print("vector recall@10 (min over sets): " + ", ".join(f"{k} {v}" for k, v in worst.items()) + f"; chosen {chosen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
