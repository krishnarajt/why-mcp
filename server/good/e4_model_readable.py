"""EXHIBIT 4 (good) -- output shaped for the reader, not for the serialiser.

DESIGN CHOICE: the tool answers the question. It does not hand over the raw
material and hope.

Same data as the bad server's 20,000-token JSON dump, rendered as a 12-line
table at ~300 tokens. What changed:

  DROPPED   surrogate ids, uuids, `_links`, nulls, base64 digests, nested
            manager and department objects with their own nested preferences.
            If the answer does not need it, it is not economy, it is noise --
            and noise is what gets quoted back to the user as a hallucinated
            field name.
  CONVERTED ISO-8601-with-microseconds -> "8d ago". Models do date arithmetic
            badly and relative time removes the need for any.
  PRECOMPUTED the success rate AND a verdict word. Do not make the model divide
            13 by 15 and then decide what counts as unhealthy -- that is a
            policy decision, and policy belongs on your server where you can
            test it.
  SORTED    worst first. Ordering is free information: "whose is worst" is
            answered by row 1 before the model reasons at all.

Rule of thumb: if a human would not want to read your tool's output, the model
is not enjoying it either.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from hr import data
from server.common import rel, table, verdict

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def register(mcp) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def payroll_health_report() -> str:
        """Payroll health for every employee in one table, worst first: last paycheck, 12-month success rate, verdict.

        Verdict is computed server-side: BLOCKED below 40% payroll success,
        UNSTABLE below 90%, otherwise healthy (or "failed last cycle" if the
        most recent paycheck failed). Use this to answer "whose payroll is
        broken" or "whose is worst".
        """
        rows = []
        for emp in data.all_employees():
            stats = data.payroll_stats(emp["id"])
            checks = data.paychecks_for_employee(emp["id"], limit=1)
            last = checks[0] if checks else None
            last_status = last["status"] if last else "-"
            rows.append(
                (
                    stats["rate"],
                    [
                        emp["name"],
                        emp["title"],
                        rel(last["issued_at"]) if last else "never",
                        last_status,
                        f"{stats['rate']:.0%} ({stats['paid']}/{stats['total']})",
                        verdict(stats["rate"], last_status),
                    ],
                )
            )
        rows.sort(key=lambda pair: pair[0])
        body = table(
            ["employee", "title", "last paycheck", "status",
             f"{data.STATS_LABEL} success", "verdict"],
            [r for _rate, r in rows],
        )
        return f"{body}\n\n(sorted worst first; 12-month window; all times UTC)"
