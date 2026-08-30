"""EXHIBIT 2 (bad) -- no truncation, no search, no size signal.

DESIGN CHOICE: `get_paycheck_trace` returns the trace. All of it. Faithfully.

Faithful is the trap. A payroll-engine trace is unbounded input, and a tool
that returns unbounded input is a tool that works perfectly in testing (where
your fixture traces are 40 lines) and detonates in production (where paycheck
9002 -- a commission-heavy sales rep with thousands of deals to price -- has a
700,532-character trace, about 236,000 tokens, more than gpt-4o-mini's entire
128k window).

There is no way for the model to ask for less, because the tool takes no
arguments that would let it. The only signal the model gets that something is
wrong is the request failing.
"""

from __future__ import annotations

from hr import data
from server.common import dumps


def register(mcp) -> None:
    @mcp.tool()
    def get_paycheck_trace(paycheck_id: int) -> str:
        """Get the payroll trace for a paycheck."""
        row = data.paycheck_by_id(paycheck_id)
        return row["trace"] if row else "null"

    @mcp.tool()
    def get_paycheck_meta(paycheck_id: int) -> str:
        """Get metadata for a paycheck."""
        rows = data.q(
            "SELECT p.id, p.status, p.error_code, p.period, p.issued_at, "
            "e.name AS employee_name FROM paychecks p "
            "JOIN employees e ON e.id = p.employee_id WHERE p.id = ?",
            (paycheck_id,),
        )
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def list_failed_paychecks(limit: int = 10) -> str:
        """List failed paychecks."""
        rows = data.q(
            "SELECT p.id, e.name AS employee_name, p.period, p.issued_at, p.error_code "
            "FROM paychecks p JOIN employees e ON e.id = p.employee_id "
            "WHERE p.status='failed' ORDER BY p.issued_at DESC LIMIT ?",
            (limit,),
        )
        return dumps([dict(r) for r in rows])
