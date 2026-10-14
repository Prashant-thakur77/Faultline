"""Live: the scale benchmark at ~1k services end to end (seed → GRAPH.COPY clean room → planted incident through
`run_incident` → sweep timing → preflight → PROFILE of the hero templates), then cleanup. About 30 s."""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))


def test_scale_1k_verdict_correct_and_graphs_cleaned(db):
    import scale

    res = scale.run_size("1k", profile_n=2, keep=False, progress=False)
    assert not res.get("skipped"), res.get("skipped")
    assert res["services"] == 1000 and res["nodes"] > 25_000 and res["edges"] > 100_000
    assert res["memory_mb"] and res["seed"]["seed_s"] > 0
    r = res["run"]
    assert r["correct"], r["why"]
    assert r["outcome"] == "CONFIRMED" and r["cause"] == res["incident"]["roles"]["cause"] and not r["error"]
    assert res["sweep_ms"]["n"] == scale.SWEEP_REPEAT and res["sweep_ms"]["eliminated"] == res["sweep_ms"]["changes"] - 1
    for tid in scale.HERO:
        x = res["templates"][tid]
        assert x.get("engine_ms_p50") is not None and not x["errors"], (tid, x)
    assert all(p["verdict"] in ("allow", "require_review", "block") for p in res["preflight"])
    assert not [g for g in db.list_graphs() if g.startswith(("golden_scale1k", "eval_scale1k_"))]
