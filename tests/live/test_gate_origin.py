"""Live: the sweep's origin test. Five extra deploys in the SAME minute on healthy services that DO have a path and
capacity to checkout: their components are measured in band while payment is anomalous, so they are not the origin.
The product still confirms the real cause confidently, and never makes a wrong confident claim."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
import harness  # noqa: E402

pytestmark = pytest.mark.live


def test_same_minute_decoys_on_healthy_dependencies_are_not_the_origin():
    r = {x["decoys"]: x for x in harness._distractor_scaling((0, 5))}
    assert r[0]["correct"] and r[0]["confident"]
    assert r[5]["correct"] and r[5]["confident"] and r[5]["outcome"] == "CONFIRMED"
    assert not any(x["wrong_confident"] for x in r.values())
