"""MCP server (Python MCP SDK `MCPServer`): every graph tool is an MCP tool. Tenant is bound per
session (env FAULTLINE_TENANT for stdio); no tool accepts a graph name.

    python -m faultline.mcp_server.server --stdio
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .. import __version__
from ..config import settings
from . import tools as T

INSTRUCTIONS = (
    "Faultline's operational context graph (FalkorDB). Read-only tools; every result carries the Cypher it ran, "
    "its params, timing, a row digest and served_by. Use causal_paths before claiming a cause (no path, no claim), "
    "impact_bound to test whether a suspect can carry the observed impact, and templates before anything else. "
    "Resources: faultline://schema (live labels, relationship types, endpoint pairs), faultline://queries (the "
    "template catalogue), faultline://weights. Prompts: investigate_incident, preflight_pr, ask_brain."
)


WRITE_TOOLS = {"remember"}   # the one MCP tool that writes: a shared note, to agentmem_<tenant> only


def register_tools(server: MCPServer, public: bool = False) -> MCPServer:
    """public=True (hosted HTTP, judges): drop INTERNAL_TOOLS, which build engine-written scratch/what-if graphs. Every hosted tool then reads only, through the tenant's read-only ACL user."""
    from ..agent.phases import INTERNAL_TOOLS, RUN_SCOPED_TOOLS
    from .titles import TITLES

    ro = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    # internal tools read the tenant graph read-only but WRITE a throwaway scratch/what-if graph (engine connection)
    scratch = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    # `remember` writes one note to the tenant's agentmem graph only (the mem_<t> ACL user), never the tenant graph
    note = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    for name, fn in T.TOOLS.items():
        if public and (name in INTERNAL_TOOLS or name in RUN_SCOPED_TOOLS):
            continue
        if public and name in WRITE_TOOLS and not settings.faultline_mcp_notes:
            continue  # the public demo stays read-only; a self-hosted HTTP server opts in with FAULTLINE_MCP_NOTES=true
        server.add_tool(fn, name=name, title=TITLES.get(name), description=(fn.__doc__ or "").strip(),
                        annotations=note if name in WRITE_TOOLS else scratch if name in INTERNAL_TOOLS else ro,
                        structured_output=True)
    from . import resources

    resources.register(server)  # faultline://schema|queries|weights + the three prompts (tenant-bound, read-only)
    return server


def build_server() -> MCPServer:
    return register_tools(MCPServer(name="faultline", title="Faultline graph tools", instructions=INSTRUCTIONS,
                                    version=__version__))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true", default=True)
    ap.parse_args()
    build_server().run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
