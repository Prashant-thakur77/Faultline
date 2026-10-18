"""Live: a bound over something the graph does not hold is unknown, never "insufficient".

A hosted MCP client (or a model) may ask impact_bound about a change id that exists only inside a run's clean room,
or mistype a component. Zero flow would read as "cannot carry the impact", which eliminates; the gate must instead
see G5 as not evaluable (Q-NODE-EXISTS names what is missing).
"""

import pytest

from faultline.graph.errors import GraphNotReady
from faultline.graph.ro import RO
from faultline.mcp_server import context
from faultline.mcp_server import tools as T

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def acme(db):
    try:
        RO("acme").require_ready()
    except (GraphNotReady, Exception) as e:
        pytest.skip(f"acme not seeded: {e}")
    tok = context.bind("acme")
    yield
    context.unbind(tok)


def test_a_suspect_outside_the_graph_gives_an_unknown_bound(acme):
    r = T.impact_bound(suspect_ids=["D-not-in-this-graph"], symptom_id="checkout", observed_share=0.5)
    assert r["verdict"] == "unknown" and r["flow_share"] is None
    assert "D-not-in-this-graph" in r["unknown_reason"] and "Q-NODE-EXISTS" in r["template"]
    # a real component with no path still answers from the flow, not from existence
    ok = T.impact_bound(suspect_ids=["recommendation"], symptom_id="checkout", observed_share=0.5)
    assert ok["verdict"] in ("insufficient", "sufficient") and "Q-NODE-EXISTS" not in ok["template"]
