"""S13 concurrency (T2): W workers race to claim one task per round (W-CLAIM-1, one conditional query) while R
read-only readers run a real template (algo.BFS blast radius) through GRAPH.RO_QUERY. Also a lost-update probe:
every worker increments one counter every round inside a single query.

Asserts: exactly 1 owner per round; counter == W × rounds (0 lost updates). Reports RO read p50/p95 with and
without the write storm. Runs on a fresh GRAPH.COPY of the golden graph (never the live tenant graph).

    PYTHONPATH=backend uv run python evals/concurrency.py [--workers 16] [--rounds 100] [--out evals/results/concurrency.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __import__("importlib.util").util.find_spec("faultline") is None:  # keep a PYTHONPATH copy (mutation check) first
    sys.path.insert(0, str(ROOT / "backend"))

from faultline.graph import client, writes  # noqa: E402
from faultline.graph import copy as gcopy  # noqa: E402
from faultline.graph.ro import RO  # noqa: E402
from faultline.graph.tenant import golden_graph  # noqa: E402


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 3)


def _reads(tenant: str, graph: str, stop: threading.Event, out: list[float], errors: list[str]) -> None:
    ro = RO(tenant, graph)
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            ro.run("Q-BLAST-1", {"id": "payment"})
            out.append((time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}"[:200])


def run(tenant: str = "acme", workers: int = 16, rounds: int = 100, readers: int = 4) -> dict:
    db = client.engine()
    graph = f"eval_{tenant}_conc_{uuid.uuid4().hex[:6]}"
    gcopy.copy_graph(db, golden_graph(tenant), graph)
    try:
        # read latency without writes (reference)
        quiet: list[float] = []
        stop, errs = threading.Event(), []
        th = [threading.Thread(target=_reads, args=(tenant, graph, stop, quiet, errs)) for _ in range(readers)]
        [t.start() for t in th]
        time.sleep(1.0)
        stop.set()
        [t.join() for t in th]
        # the race
        busy: list[float] = []
        stop = threading.Event()
        rth = [threading.Thread(target=_reads, args=(tenant, graph, stop, busy, errs)) for _ in range(readers)]
        [t.start() for t in rth]
        winners: dict[int, list[str]] = {r: [] for r in range(rounds)}
        lock = threading.Lock()
        barrier = threading.Barrier(workers)
        werr: list[str] = []

        def worker(i: int) -> None:
            g = client.engine().select_graph(graph)
            agent = f"agent-{i:02d}"
            for r in range(rounds):
                barrier.wait()
                try:
                    if writes.claim_task(g, task=f"task-{r:04d}", agent=agent, role="specialist", tenant=tenant):
                        with lock:
                            winners[r].append(agent)
                    writes.bump_counter(g, counter="counter-s13")
                except Exception as e:  # noqa: BLE001
                    werr.append(f"{type(e).__name__}: {e}"[:200])

        t0 = time.perf_counter()
        wth = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        [t.start() for t in wth]
        [t.join() for t in wth]
        storm_s = time.perf_counter() - t0
        stop.set()
        [t.join() for t in rth]
        g = db.select_graph(graph)
        counter = g.ro_query("MATCH (c:Task {id:'counter-s13'}) RETURN c.n").result_set[0][0]
        owners = dict(g.ro_query("MATCH (t:Task) WHERE t.id STARTS WITH 'task-' RETURN t.id, t.owner").result_set)
        claimed_by = g.ro_query("MATCH (t:Task)-[:CLAIMED_BY]->(a:Agent) WHERE t.id STARTS WITH 'task-' "
                                "RETURN t.id, count(a)").result_set
        one_owner = sum(1 for r in range(rounds) if len(winners[r]) == 1 and owners.get(f"task-{r:04d}") == winners[r][0])
        out = {
            "scenario": "S13", "tenant": tenant, "workers": workers, "rounds": rounds, "readers": readers,
            "rounds_with_exactly_one_owner": one_owner, "max_claim_edges_per_task": max((c for _, c in claimed_by), default=0),
            "counter_expected": workers * rounds, "counter_actual": int(counter),
            "lost_updates": workers * rounds - int(counter), "write_errors": len(werr), "read_errors": len(errs),
            "claims_per_s": round(workers * rounds / storm_s, 1), "storm_s": round(storm_s, 2),
            "ro_read_ms": {"quiet": {"n": len(quiet), "p50": _pct(quiet, 0.5), "p95": _pct(quiet, 0.95)},
                           "during_writes": {"n": len(busy), "p50": _pct(busy, 0.5), "p95": _pct(busy, 0.95),
                                             "mean": round(statistics.fmean(busy), 3) if busy else 0.0}},
            "engine": "FalkorDB (pinned; see backend/faultline/graph/algo/resolved.json)",
            "sample_errors": (werr + errs)[:3],
        }
        out["passed"] = (one_owner == rounds and out["lost_updates"] == 0 and out["max_claim_edges_per_task"] == 1
                         and not werr)
        return out
    finally:
        gcopy.delete_if_exists(db, graph)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--readers", type=int, default=4)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    res = run(a.tenant, a.workers, a.rounds, a.readers)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
