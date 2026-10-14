"""Live: fixes from the 2026-10-13 pre-release review."""

import anyio
import pytest

from faultline import scenario
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import copy as gcopy
from faultline.graph.ro import RO

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def s1():
    p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=True))
    yield p, res
    gcopy.delete_if_exists(gclient.engine(), p.graph)


def test_the_gate_keeps_the_hypothesize_scores(s1):
    """The gate and the sweep change a hypothesis' status, never its HYPOTHESIZE score (was: every suspect 0.00)."""
    p, res = s1
    rows = RO(p.tenant, p.graph).run("Q-HYP-1", {"inc": p.incident_id}).rows
    swept = [r for r in rows if r["status"] in ("confirmed", "eliminated")]
    assert swept and all(r["score"] and r["score"] > 0 for r in swept), rows
    assert len({r["score"] for r in swept}) > 1   # ranked scores, not one default
