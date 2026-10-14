"""A graph outage inside a specialist fails the run loudly; it is never turned into an 'insufficient' report."""

import anyio
import pytest

from faultline.agent.specialists.base import SpecialistCtx, raise_if_outage
from faultline.graph.errors import GraphTimeout, GraphUnavailable


@pytest.mark.parametrize("err,exc", [
    ("unavailable: FalkorDB unreachable", GraphUnavailable),          # MCP guard (GraphUnavailable), data tools
    ("GraphTimeout: Q-GATE-3: Query timed out", GraphTimeout),         # MCP guard (GraphTimeout)
    ("unavailable: Q-BASE-1: Query timed out", GraphTimeout),          # data tools wrap every GraphError
])
def test_outage_errors_raise(err, exc):
    with pytest.raises(exc):
        raise_if_outage("metric_window", {"error": err})


@pytest.mark.parametrize("out", [{"error": "invalid arguments: id too long"}, {"error": "unknown tool 'x'"},
                                 {"rows": []}, {"error": None}])
def test_other_results_are_returned_to_the_specialist(out):
    raise_if_outage("metric_window", out)


def test_the_specialist_context_raises_instead_of_returning_the_outage():
    class Box:
        async def call(self, name, args, only=None, caller=None):
            return {"error": "unavailable: FalkorDB unreachable"}

    ctx = SpecialistCtx("telemetry", Box(), run=None, packet={})
    with pytest.raises(GraphUnavailable):
        anyio.run(lambda: ctx.call("metric_window", {"target_id": "checkout"}))
