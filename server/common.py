"""Helpers shared by both servers.

Every tool on both servers returns a **string**. That is a deliberate demo
choice: the scoreboard measures tokens, and returning text means what you read
in the trace is exactly what the model was charged for. No hidden structured
content, no ambiguity about who paid for what.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hr import data


def rel(when_iso: str) -> str:
    then = datetime.fromisoformat(when_iso.replace("Z", "+00:00")).astimezone(UTC)
    secs = int((data.now() - then).total_seconds())
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def dumps(obj) -> str:
    """The bad servers' house style: pretty-printed JSON, every field included."""
    return json.dumps(obj, indent=2, default=str)


def table(headers: list[str], rows: list[list[str]]) -> str:
    """The good servers' house style: a markdown table the model reads in one pass."""
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(headers)]
    out = [" | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("-|-".join("-" * w for w in widths))
    for r in rows:
        out.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def error_lines(trace: str, limit: int = 6) -> list[str]:
    hits = [ln for ln in trace.splitlines() if any(k in ln for k in ("ERROR", "FATAL", "REJECTED"))]
    return hits[-limit:]


def verdict(rate: float, last_status: str) -> str:
    if rate < 0.4:
        return "BLOCKED"
    if rate < 0.9:
        return "UNSTABLE"
    return "failed last cycle" if last_status == "failed" else "healthy"


SCHEMA_DOC = """\
HR / payroll database schema
  departments(id, name, cost_center, location, head)
  employees(id, name, email, title, department_id, manager_id, hired_at,
            status, salary, payroll_hold)
  paychecks(id, employee_id, period, issued_at, settled_at, status, net_pay,
            error_code, trace)
  org_changes(id, area, kind, effective_at, changed_by, notes)
  hr_cases(id, title, opened_at, closed_at, severity, resolution)

paychecks.status is 'paid' or 'failed'. paychecks.period is a semi-monthly
label such as '2026-08-B' ('A' = the 1st-15th, 'B' = the 16th onwards).
employees.payroll_hold is 1 when payroll is suspended for that person.

All timestamps are stored and returned in UTC (ISO-8601, trailing 'Z').
Pay periods and payroll close times are also evaluated in UTC.
"""
