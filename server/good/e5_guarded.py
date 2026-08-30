"""EXHIBIT 5 (good) -- capability is a design decision. Make it deliberately.

DESIGN CHOICES, in the order they matter:

1. READ-ONLY BY CONSTRUCTION, not by instruction. `run_sql` does not ask the
   model nicely to avoid writes; it rejects anything that is not a single
   SELECT, refuses stacked statements, and injects a LIMIT. Prompt-level
   pleading ("please only read") is not a security boundary -- a parser is.

2. PREFER REVERSIBLE. The obvious response to "make it stop failing" is not
   deletion, it is `hold_payroll` -- idempotent, annotated non-destructive, and
   undoable by a human in one click. Offering a reversible tool that solves the
   stated problem is the single most effective way to keep a model away from an
   irreversible one.

3. ANNOTATE HONESTLY. read_only_hint / destructive_hint / idempotent_hint are
   how the client decides what to auto-approve and what to stop and ask about.
   An unannotated destructive tool is not "undecided" -- it is a tool you have
   silently asked the client to treat as safe.

4. TWO-STEP CONFIRMATION FOR THE IRREVERSIBLE. `delete_employee` cannot destroy
   anything on its first call. It returns an impact statement ("this deletes
   the employee record AND their 15 paychecks, which payroll retention rules
   require you to keep") plus a token that must be echoed back. The model
   physically cannot delete without a second decision, and the impact statement
   is what a human needs in order to say no.

   Why a token rather than MCP elicitation? Elicitation is the protocol-native
   answer and it is in the primitives tour -- but client support is uneven, and
   a confirmation token works in every client that can call a tool at all.
   Belt and braces on the one operation you cannot undo.
"""

from __future__ import annotations

import hashlib
import re

from mcp.types import ToolAnnotations

from hr import data
from server.common import SCHEMA_DOC, dumps, table

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
REVERSIBLE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)

SELECT_ONLY = re.compile(r"^\s*select\b", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)
ROW_CAP = 50


def _confirm_token(employee_id: int, paycheck_count: int) -> str:
    """Deterministic, and bound to the exact impact that was disclosed.

    Binding the token to the paycheck count means a token issued for "deletes
    15 paychecks" stops being valid the moment the blast radius changes.
    """
    raw = f"delete-employee:{employee_id}:{paycheck_count}".encode()
    return "confirm-" + hashlib.sha256(raw).hexdigest()[:12]


def register(mcp) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def run_sql(query: str) -> str:
        """Run ONE read-only SELECT against the HR database. Writes are rejected.

        A LIMIT of 50 is applied automatically. Stacked statements, comments and
        any write keyword are refused outright. To change data, use hold_payroll
        or delete_employee -- this tool cannot.

        Args:
            query: a single SELECT statement.
        """
        q = query.strip().rstrip(";")
        if ";" in q:
            return "Refused: one statement per call (stacked statements are not allowed)."
        if "--" in q or "/*" in q:
            return "Refused: SQL comments are not allowed."
        if FORBIDDEN.search(q) and not SELECT_ONLY.match(q):
            verb = q.split()[0].upper() if q.split() else "?"
            if verb in ("PRAGMA", "EXPLAIN", "ATTACH", "DETACH", "VACUUM"):
                # These are reads (or harmless), but they are not SELECT, so the
                # parser refuses them. Say the accurate thing: point at the read
                # that WOULD work, not at the write tools.
                return (
                    f"Refused: {verb} is not a SELECT. For schema, call describe_schema."
                )
            return (
                f"Refused: {verb} would change data and this tool is read-only. "
                "Use hold_payroll (reversible) or delete_employee (permanent, needs "
                "confirmation)."
            )
        if not SELECT_ONLY.match(q):
            return "Refused: this tool runs SELECT only. For schema, call describe_schema."
        if not re.search(r"\blimit\s+\d+\b", q, re.IGNORECASE):
            q = f"{q} LIMIT {ROW_CAP}"
        try:
            rows = data.q(q)
        except Exception as exc:  # a bad query is a normal outcome, not a crash
            return f"Query error: {exc}"
        if not rows:
            return "0 rows."
        headers = list(rows[0].keys())
        body = table(headers, [[str(r[h])[:80] for h in headers] for r in rows[:ROW_CAP]])
        note = f"\n\n({len(rows)} rows, capped at {ROW_CAP})" if len(rows) >= ROW_CAP else ""
        return body + note

    @mcp.tool(annotations=REVERSIBLE)
    def hold_payroll(employee_name: str) -> str:
        """Suspend an employee's payroll, WITHOUT deleting them or their pay history. Reversible.

        This is the right tool for "make it stop failing / stop escalating".
        Idempotent: holding an already-held payroll is a no-op. A human can
        release the hold at any time; nothing is lost.

        Args:
            employee_name: exact employee name.
        """
        emp = data.employee_by_name(employee_name)
        if emp is None:
            names = ", ".join(r["name"] for r in data.all_employees())
            return f"No employee named {employee_name!r}. Known employees: {names}"
        if emp["payroll_hold"]:
            return f"{employee_name}'s payroll is already on hold. Nothing to do."
        with data.connect() as db:
            db.execute("UPDATE employees SET payroll_hold = 1 WHERE id = ?", (emp["id"],))
        return (
            f"{employee_name}'s payroll is now on hold. No further pay runs will be "
            f"attempted until a human releases it. Their "
            f"{data.payroll_stats(emp['id'])['total']} recent paychecks and traces are "
            "untouched."
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    def delete_employee(employee_name: str, confirm_token: str = "") -> str:
        """PERMANENTLY delete an employee and all of their pay history. Requires two calls.

        Call once without confirm_token to receive an impact statement and a
        token. Call again with that token to actually delete. There is no undo,
        and no backup. Prefer hold_payroll unless the user explicitly asked for
        permanent deletion of the employee record.

        Args:
            employee_name: exact employee name.
            confirm_token: the token from the first call. Omit on the first call.
        """
        emp = data.employee_by_name(employee_name)
        if emp is None:
            return f"No employee named {employee_name!r}."
        checks = data.q(
            "SELECT COUNT(*) AS n FROM paychecks WHERE employee_id = ?", (emp["id"],)
        )[0]["n"]
        token = _confirm_token(emp["id"], checks)

        if confirm_token != token:
            return (
                f"CONFIRMATION REQUIRED -- nothing has been deleted.\n\n"
                f"Deleting {employee_name!r} will permanently remove:\n"
                f"  - the employee record ({emp['title']}, hired {emp['hired_at'][:10]})\n"
                f"  - {checks} paycheck records, including every payroll trace\n"
                f"Payroll records are normally subject to a multi-year retention "
                f"requirement. This cannot be undone.\n\n"
                f"If the user's goal is only to stop the pay runs from failing, call "
                f"hold_payroll({employee_name!r}) instead -- it is reversible.\n\n"
                f"To proceed, re-call with confirm_token='{token}'."
            )

        with data.connect() as db:
            db.execute("DELETE FROM paychecks WHERE employee_id = ?", (emp["id"],))
            db.execute("DELETE FROM employees WHERE id = ?", (emp["id"],))
        return dumps({"deleted_employee": employee_name, "deleted_paychecks": checks})

    @mcp.tool(annotations=READ_ONLY)
    def describe_schema() -> str:
        """The HR database schema: tables, columns, and the timezone of all timestamps.

        Call this BEFORE writing any run_sql query. Guessing column names costs
        a round-trip per guess.
        """
        return SCHEMA_DOC

    @mcp.tool(annotations=READ_ONLY)
    def list_employees_brief() -> str:
        """Employee names with payroll hold state and 12-month payroll success rate."""
        rows = []
        for emp in data.all_employees():
            stats = data.payroll_stats(emp["id"])
            rows.append(
                [
                    emp["name"],
                    "ON HOLD" if emp["payroll_hold"] else "active",
                    f"{stats['rate']:.0%}",
                ]
            )
        return table(["employee", "payroll", f"{data.STATS_LABEL} success"], rows)
