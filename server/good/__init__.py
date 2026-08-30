"""The good server.

Same shape as the bad one, same scoping rule, same empty `instructions`.
Exhibit 7 deliberately re-exports the bad server's module: there is no fix.

`exhibit=0` builds the primitives tour (resources / prompts / sampling /
elicitation) plus exhibit 1's tools, because the `payroll_triage` prompt refers to them.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from server.good import (
    e1_task_shaped,
    e2_truncated,
    e3_precise_descriptions,
    e4_model_readable,
    e5_guarded,
    e6_curated,
    e7_brittle,
    primitives,
)

EXHIBITS = {
    1: e1_task_shaped,
    2: e2_truncated,
    3: e3_precise_descriptions,
    4: e4_model_readable,
    5: e5_guarded,
    6: e6_curated,
    7: e7_brittle,
}


def build(exhibit: int) -> MCPServer:
    mcp = MCPServer(name=f"hr-good-e{exhibit}", version="1.0.0")
    if exhibit == 0:
        e1_task_shaped.register(mcp)
        e5_guarded.register(mcp)
        primitives.register(mcp)
    else:
        EXHIBITS[exhibit].register(mcp)
    return mcp
