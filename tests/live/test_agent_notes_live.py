"""Live (T2): the investigating agent reads and writes the shared notes, and the gate never notices.

An agent leaves a lead near checkout; Faultline's run on S1 with share_notes reads it at RECALL (shown as a lead,
recorded as a tool call with nothing marked as seen) and leaves its own verdict note about the proof chain. A second
run sees the first run's verdict as a lead. The gate's outcome, cause and chain are identical with notes on and off,
and an eval-style run (notes off) makes no notes call at all.
"""

from __future__ import annotations

import anyio
import pytest

from faultline import scenario
from faultline.agent.loop import BaselineInvestigator
from faultline.graph import client as gclient
from faultline.graph import udf
from faultline.memory import notes

pytestmark = pytest.mark.live


def _run(share: bool):
    _p, res = anyio.run(lambda: scenario.run("S1", BaselineInvestigator(), set_mode=False, keep=False,
                                             share_notes=share))
    return res


@pytest.fixture(scope="module")
def runs(db):
    udf.load_udfs(db.connection)
    notes.ensure_memory_graph("acme")
    lead = notes.remember("acme", principal="test-agent-a", name="agent-a", kind="lead", about=["checkout", "payment"],
                          text="checkout errors started right after a payment deploy; worth a look")
    made = [lead["id"]]
    try:
        off = _run(False)
        on1 = _run(True)
        on2 = _run(True)
        made += [r.note["id"] for r in (on1, on2) if r.note and r.note.get("id")]
        yield lead, off, on1, on2
    finally:
        gclient.engine().select_graph("agentmem_acme").query("MATCH (n:Note) WHERE n.id IN $ids DETACH DELETE n",
                                                            {"ids": made})


def test_the_gate_is_identical_with_notes_on_and_off(runs):
    _, off, on1, _ = runs
    assert off.outcome == on1.outcome == "CONFIRMED" and off.cause_id == on1.cause_id
    assert off.gate["chain"] == on1.gate["chain"]
    assert "leads" not in (off.recall or {}) and off.note is None          # an eval-style run never touches notes


def test_the_run_reads_other_agents_leads_and_leaves_its_verdict(runs):
    lead, _, on1, on2 = runs
    assert lead["id"] in [x["id"] for x in on1.recall["leads"]]
    assert on1.note["kind"] == "verdict" and set(on1.note["about"]) & {"payment", "checkout"}
    assert on1.note["id"] in [x["id"] for x in on2.recall["leads"]]       # the next run starts from it
