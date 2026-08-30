"""EXHIBIT 6 (bad) -- forty-seven tools, and you pay for all of them every turn.

DESIGN CHOICE: never delete a tool. Every capability anyone ever asked for
stays registered, because removing one might break someone.

The cost is invisible in code review and brutal in production: `tools/list` is
serialised into the system prompt of EVERY request. Ask "what timezone are the
payroll timestamps in?" -- a question needing one tiny tool -- and you have
already spent thousands of tokens describing forty-six tools you will not call.

Worse than the tokens: tool choice degrades. With forty-seven options, several
of them near-synonyms (`get_config`/`get_settings`, `list_alerts`/`list_events`),
the model wanders. It calls two or three wrong tools before the right one.

This exhibit registers every bad tool from exhibits 1-5 plus the usual pile of
accreted extras. The good server ships seven.
"""

from __future__ import annotations

from hr import data
from server.bad import (
    e1_endpoint_shaped,
    e2_no_truncation,
    e3_vague_descriptions,
    e4_raw_json,
    e5_unguarded,
)
from server.common import dumps


def register(mcp) -> None:
    # Everything from the other exhibits, all live at once.
    for mod in (
        e1_endpoint_shaped,
        e2_no_truncation,
        e3_vague_descriptions,
        e4_raw_json,
        e5_unguarded,
    ):
        mod.register(mcp)

    # describe_schema arrives with e5. Note what that means: on a 47-tool
    # server, you cannot tell by reading this file which tools you have.

    # ---- and now the accretion: tools nobody removed ----

    @mcp.tool()
    def list_locations() -> str:
        """List locations."""
        rows = data.q("SELECT DISTINCT location FROM departments ORDER BY location")
        return dumps([r["location"] for r in rows])

    @mcp.tool()
    def get_settings(key: str = "") -> str:
        """Get settings."""
        return dumps({"trace_retention_days": 365, "timezone": "UTC", "escalations": True})

    @mcp.tool()
    def get_config(key: str = "") -> str:
        """Get config."""
        return dumps({"trace_retention_days": 365, "timezone": "UTC", "escalations": True})

    @mcp.tool()
    def set_config(key: str, value: str) -> str:
        """Set config."""
        return dumps({"ok": True, "key": key, "value": value})

    @mcp.tool()
    def list_alerts(limit: int = 20) -> str:
        """List alerts."""
        return dumps([])

    @mcp.tool()
    def list_events(limit: int = 20) -> str:
        """List events."""
        return dumps([])

    @mcp.tool()
    def ack_alert(alert_id: int) -> str:
        """Acknowledge an alert."""
        return dumps({"ok": True})

    @mcp.tool()
    def list_webhooks() -> str:
        """List webhooks."""
        return dumps([])

    @mcp.tool()
    def get_webhook(webhook_id: int) -> str:
        """Get a webhook."""
        return dumps(None)

    @mcp.tool()
    def list_attachments(paycheck_id: int) -> str:
        """List attachments for a paycheck."""
        return dumps([])

    @mcp.tool()
    def get_cost_center_budget(cost_center: str = "CC-4100") -> str:
        """Get a cost center budget."""
        return dumps({"cost_center": cost_center, "limit_usd": 200000, "committed_usd": 200000})

    @mcp.tool()
    def list_tags(employee_id: int) -> str:
        """List tags for an employee."""
        return dumps([])

    @mcp.tool()
    def get_version() -> str:
        """Get the server version."""
        return dumps({"version": "1.0.0"})

    @mcp.tool()
    def ping() -> str:
        """Ping."""
        return "pong"

    @mcp.tool()
    def get_time() -> str:
        """Get the current server time."""
        return data.iso(data.now())

    @mcp.tool()
    def list_pay_periods() -> str:
        """List pay periods."""
        rows = data.q("SELECT DISTINCT period FROM paychecks ORDER BY period DESC LIMIT 12")
        return dumps([r["period"] for r in rows])

    @mcp.tool()
    def validate_email(address: str) -> str:
        """Validate an email address."""
        return dumps({"valid": "@" in address and "." in address.split("@")[-1]})
