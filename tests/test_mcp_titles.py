"""Every MCP tool carries a human title (the question it answers); names are unchanged."""

from faultline.mcp_server import tools as T
from faultline.mcp_server.titles import TITLES


def test_every_tool_has_a_title_and_no_title_names_a_missing_tool():
    assert set(TITLES) == set(T.TOOLS)
    assert all(t and len(t) <= 90 for t in TITLES.values())
