"""EXHIBIT 1 (good) -- task-shaped tools.

DESIGN CHOICE: name the tools after the questions people actually ask, not the
tables you happen to store. Do the joins on the server, where they cost
microseconds, instead of in the model, where each hop costs a full round-trip
and re-bills the entire conversation.

`diagnose_payroll_failure` is one call that answers "why did X's paycheck
fail?" completely:
  - finds the failing paycheck
  - pulls only the ERROR/FATAL lines out of the payroll trace
  - correlates org changes in the 72h window before it
  - surfaces matching closed HR cases
Four queries the model never has to think about, and a briefing it can read in
one pass.

The test for a good tool is not "does it expose the data" -- it is "does one
call finish a thought?" Three tools that finish thoughts beat nineteen that
expose tables.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from hr import data
from server.common import error_lines, rel, table

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def register(mcp) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def diagnose_payroll_failure(employee_name: str, since_days: int = 30) -> str:
        """Explain why an employee's paycheck failed: the error, what changed in the org just before it, and prior cases.

        Use this as the FIRST call for any "why did X's pay fail / bounce /
        get escalated" question. It already correlates paychecks, payroll
        traces, org changes and closed case files, so you do not need to fetch
        those separately.

        Args:
            employee_name: exact employee name, e.g. "Priya Raman". Call list_employees first if unsure.
            since_days: how far back to look for a failed paycheck. Default 30.
        """
        emp = data.employee_by_name(employee_name)
        if emp is None:
            names = ", ".join(r["name"] for r in data.all_employees())
            return f"No employee named {employee_name!r}. Known employees: {names}"

        failures = [
            p for p in data.recent_failures(since_days) if p["employee_id"] == emp["id"]
        ]
        if not failures:
            return f"{employee_name} has no failed paychecks in the last {since_days} days."

        check = data.paycheck_by_id(failures[0]["id"])
        out = [
            f"## {employee_name}'s paycheck failed",
            f"paycheck {check['id']}, period {check['period']}, issued "
            f"{rel(check['issued_at'])}, error code {check['error_code']}",
            "",
            "### error lines from the payroll trace",
            *(f"  {ln}" for ln in error_lines(check["trace"], limit=4)),
        ]

        changes = data.org_changes_before(check["issued_at"], hours=72)
        out += ["", "### org changes in the 72h before the pay run"]
        if changes:
            out.append(
                table(
                    ["area", "kind", "when", "by", "notes"],
                    [
                        [c["area"], c["kind"], rel(c["effective_at"]), c["changed_by"], c["notes"]]
                        for c in changes
                    ],
                )
            )
        else:
            out.append("  none")

        # Search history with the employee name AND the loudest error keyword.
        keyword = next(
            (
                k
                for k in ("budget", "deadlock", "rate table", "cost center", "deduction")
                if k in check["trace"].lower()
            ),
            employee_name,
        )
        prior = {c["id"]: c for c in data.search_hr_cases(employee_name)}
        prior.update({c["id"]: c for c in data.search_hr_cases(keyword)})
        out += ["", "### matching past HR cases"]
        if prior:
            for case in prior.values():
                out.append(f"  [{case['severity']}] {case['title']} ({rel(case['opened_at'])})")
                out.append(f"      {case['resolution'][:400]}")
        else:
            out.append("  none")
        return "\n".join(out)

    @mcp.tool(annotations=READ_ONLY)
    def list_employees(only_unhealthy: bool = False) -> str:
        """List employees with their department, last paycheck, and 12-month payroll success rate.

        Args:
            only_unhealthy: if true, return only people below 90% payroll success or whose last paycheck failed.
        """
        rows = []
        for emp in data.all_employees():
            stats = data.payroll_stats(emp["id"])
            checks = data.paychecks_for_employee(emp["id"], limit=1)
            last = checks[0] if checks else None
            unhealthy = stats["rate"] < 0.9 or (last and last["status"] == "failed")
            if only_unhealthy and not unhealthy:
                continue
            dept = data.q(
                "SELECT name FROM departments WHERE id = ?", (emp["department_id"],)
            )[0]["name"]
            rows.append(
                [
                    emp["name"],
                    emp["title"],
                    dept,
                    rel(last["issued_at"]) if last else "never",
                    last["status"] if last else "-",
                    f"{stats['rate']:.0%}",
                ]
            )
        if not rows:
            return "Everyone's payroll is healthy."
        return table(
            ["employee", "title", "department", "last paycheck", "status",
             f"{data.STATS_LABEL} success"],
            rows,
        )

    @mcp.tool(annotations=READ_ONLY)
    def recent_payroll_failures(days: int = 30) -> str:
        """Every failed paycheck across all employees in the last N days, newest first.

        Args:
            days: lookback window. Default 30.
        """
        rows = data.recent_failures(days)
        if not rows:
            return f"No payroll failures in the last {days} days."
        return table(
            ["paycheck", "employee", "period", "when", "error"],
            [
                [r["id"], r["employee_name"], r["period"], rel(r["issued_at"]), r["error_code"]]
                for r in rows
            ],
        )
