"""EXHIBIT 1 (bad) -- endpoint-shaped tools.

DESIGN CHOICE: mirror the REST API one-to-one. Nineteen tools, each a thin
wrapper over a single query, each returning raw JSON.

This is the most common way MCP servers are built, because it is the most
obvious: you already have routes, so you expose routes. It feels complete --
every field is reachable! -- and it pushes the entire join onto the model.

To answer "why did Priya Raman's paycheck fail last cycle?" the model must:
  list_employees -> find the id -> list_paychecks -> find last cycle's paycheck
  -> get_paycheck -> get_paycheck_trace -> list_org_changes -> get_org_change
Eight round-trips, each paying full input tokens for the whole conversation
so far. The good server does it in one.
"""

from __future__ import annotations

from hr import data
from server.common import dumps


def register(mcp) -> None:
    @mcp.tool()
    def list_employees() -> str:
        """List employees."""
        return dumps([dict(r) for r in data.all_employees()])

    @mcp.tool()
    def get_employee(employee_id: int) -> str:
        """Get an employee by id."""
        rows = data.q("SELECT * FROM employees WHERE id = ?", (employee_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def get_employee_by_name(name: str) -> str:
        """Get an employee by name."""
        row = data.employee_by_name(name)
        return dumps(dict(row)) if row else "null"

    @mcp.tool()
    def get_employee_manager(employee_id: int) -> str:
        """Get the manager id of an employee."""
        rows = data.q("SELECT manager_id FROM employees WHERE id = ?", (employee_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def get_employee_department(employee_id: int) -> str:
        """Get the department id of an employee."""
        rows = data.q("SELECT department_id FROM employees WHERE id = ?", (employee_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def list_paychecks(employee_id: int, limit: int = 20, offset: int = 0) -> str:
        """List paychecks for an employee."""
        rows = data.q(
            "SELECT id, employee_id, period, issued_at, settled_at, status, net_pay, "
            "error_code FROM paychecks WHERE employee_id = ? "
            "ORDER BY issued_at DESC LIMIT ? OFFSET ?",
            (employee_id, limit, offset),
        )
        return dumps([dict(r) for r in rows])

    @mcp.tool()
    def list_paycheck_ids(employee_id: int) -> str:
        """List paycheck ids for an employee."""
        rows = data.q(
            "SELECT id FROM paychecks WHERE employee_id = ? ORDER BY issued_at DESC",
            (employee_id,),
        )
        return dumps([r["id"] for r in rows])

    @mcp.tool()
    def count_paychecks(employee_id: int) -> str:
        """Count paychecks for an employee."""
        rows = data.q("SELECT COUNT(*) AS n FROM paychecks WHERE employee_id = ?", (employee_id,))
        return dumps(dict(rows[0]))

    @mcp.tool()
    def get_paycheck(paycheck_id: int) -> str:
        """Get a paycheck by id."""
        rows = data.q(
            "SELECT id, employee_id, period, issued_at, settled_at, status, net_pay, "
            "error_code FROM paychecks WHERE id = ?",
            (paycheck_id,),
        )
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def get_paycheck_trace(paycheck_id: int) -> str:
        """Get the payroll trace for a paycheck."""
        row = data.paycheck_by_id(paycheck_id)
        return row["trace"] if row else "null"

    @mcp.tool()
    def get_paycheck_status(paycheck_id: int) -> str:
        """Get the status of a paycheck."""
        rows = data.q("SELECT status FROM paychecks WHERE id = ?", (paycheck_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def get_paycheck_error_code(paycheck_id: int) -> str:
        """Get the error code of a paycheck."""
        rows = data.q("SELECT error_code FROM paychecks WHERE id = ?", (paycheck_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def list_org_changes(limit: int = 20) -> str:
        """List org changes."""
        rows = data.q(
            "SELECT * FROM org_changes ORDER BY effective_at DESC LIMIT ?", (limit,)
        )
        return dumps([dict(r) for r in rows])

    @mcp.tool()
    def get_org_change(change_id: int) -> str:
        """Get an org change by id."""
        rows = data.q("SELECT * FROM org_changes WHERE id = ?", (change_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def list_hr_cases() -> str:
        """List HR cases."""
        rows = data.q(
            "SELECT id, title, opened_at, severity FROM hr_cases ORDER BY opened_at DESC"
        )
        return dumps([dict(r) for r in rows])

    @mcp.tool()
    def get_hr_case(case_id: int) -> str:
        """Get an HR case by id."""
        rows = data.q("SELECT * FROM hr_cases WHERE id = ?", (case_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def list_departments() -> str:
        """List departments."""
        return dumps([dict(r) for r in data.q("SELECT * FROM departments ORDER BY id")])

    @mcp.tool()
    def get_department(department_id: int) -> str:
        """Get a department by id."""
        rows = data.q("SELECT * FROM departments WHERE id = ?", (department_id,))
        return dumps(dict(rows[0])) if rows else "null"

    @mcp.tool()
    def health() -> str:
        """Health check."""
        return dumps({"ok": True})
