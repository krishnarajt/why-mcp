"""EXHIBIT 6 (good) -- a curated surface. Seven tools instead of forty-seven.

DESIGN CHOICE: treat the tool list as a budget, not a catalogue.

Every registered tool's name, description and JSON schema is serialised into
the system prompt of EVERY request, whether or not it is called. That is a
fixed tax on every conversation, paid before the user's first word. Forty-seven
tools here cost ~3,000 tokens of pure overhead; seven cost ~1,000.

The tokens are the smaller half of the win. The bigger half is tool choice:
near-synonyms (`get_config` vs `get_settings`, `list_alerts` vs `list_events`)
force the model to guess, and guesses cost round-trips. Fewer, sharper tools
make the right call obvious.

The discipline that gets you here: for each tool ask "which question does this
finish?" If two tools finish the same question, delete one. If a tool finishes
no question on its own, it belongs inside another tool, not beside it.

This module composes the good modules rather than redefining their tools --
which is itself the point. Curation is a registration decision, so it should
be visible in one file you can read top to bottom.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from server.common import SCHEMA_DOC
from server.good import e1_task_shaped, e3_precise_descriptions, e4_model_readable


def register(mcp) -> None:
    # diagnose_payroll_failure, list_employees, recent_payroll_failures
    e1_task_shaped.register(mcp)
    # search_pay_traces, search_hr_cases
    e3_precise_descriptions.register(mcp)
    # payroll_health_report
    e4_model_readable.register(mcp)

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
    )
    def describe_schema() -> str:
        """The HR database schema and its conventions, including the timezone of all timestamps."""
        return SCHEMA_DOC
