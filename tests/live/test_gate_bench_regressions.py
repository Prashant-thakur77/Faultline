"""Live: the ten generated gate cases that failed before the M13 gate fixes, pinned as regressions.
G2 (6): a change on a component with nothing upstream was never proposed (Q-SUS-1 lost the symptom row).
abstain (4): a bystander deploy was confirmed when the anomaly showed only at the symptom (now G4 origin → not confident).
Each runs on its own clean room through the real intake path (evals/gate_bench.py)."""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

FIXED = ["gb002", "gb003", "gb005", "gb011", "gb016", "gb020", "gb068", "gb069", "gb073", "gb082"]


@pytest.fixture(scope="module")
def cases(db):
    import gate_bench

    by_id = {c["id"]: c for c in gate_bench.generate(gate_bench.PLAN, gate_bench.SEED)}
    return gate_bench, by_id


@pytest.mark.parametrize("cid", FIXED)
def test_previously_failing_bench_case_now_correct(cases, cid):
    gate_bench, by_id = cases
    r = gate_bench.run_case(by_id[cid])
    assert r["correct"], f"{cid} ({r['category']}): {r['why']}"
    if r["category"] == "abstain":   # no change may be blamed with confidence when the origin had no change
        assert not (r["got"]["outcome"] == "CONFIRMED" and r["got"].get("confident"))
