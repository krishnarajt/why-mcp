"""The bad server.

One MCPServer, built with only the tools for the exhibit under test. Scoping
matters: if every bad tool were always registered, exhibit 1's "too many
round-trips" lesson would be confounded by exhibit 6's "too many tools"
lesson. Each exhibit gets a clean room.

Exhibit 6 is the exception -- its lesson IS the union, so it loads everything.

Neither server sets `instructions`. Server instructions are a real lever, but
leaving them empty on both sides keeps tool design the only variable.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from server.bad import (
    e1_endpoint_shaped,
    e2_no_truncation,
    e3_vague_descriptions,
    e4_raw_json,
    e5_unguarded,
    e6_tool_bloat,
    e7_brittle,
)

EXHIBITS = {
    1: e1_endpoint_shaped,
    2: e2_no_truncation,
    3: e3_vague_descriptions,
    4: e4_raw_json,
    5: e5_unguarded,
    6: e6_tool_bloat,
    7: e7_brittle,
}


def build(exhibit: int) -> MCPServer:
    # warn_on_duplicate_tools=False because exhibit 6 genuinely registers the
    # same name twice (e1 and e2 both define get_paycheck_trace). That collision is
    # the exhibit, not a mistake -- a 47-tool server nobody prunes really does
    # end up with two tools fighting over one name, and the second silently loses.
    mcp = MCPServer(
        name=f"hr-bad-e{exhibit}", version="1.0.0", warn_on_duplicate_tools=False
    )
    EXHIBITS[exhibit].register(mcp)
    return mcp
