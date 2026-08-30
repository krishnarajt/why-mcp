"""EXHIBIT 2 (good) -- bounded output, an honest size signal, and a way to ask again.

DESIGN CHOICE: a trace tool may never return more than it promised, and must
always say what it withheld.

Three rules, in order of importance:

1. CAP THE OUTPUT. `read_paycheck_trace` returns at most `tail` lines (default
   80, hard max 400). 236,000 tokens becomes ~900. The answer is in the tail
   anyway -- that is where the abort lives.

2. SAY WHAT YOU TRUNCATED. The header states the real size and the fact that
   you are seeing a slice. A model that does not know it got a slice will
   confidently reason about a trace it never read.

3. GIVE IT A NEXT MOVE. The header names `grep_paycheck_trace`. Truncation
   without a search escape hatch is just data loss; truncation *plus* search is
   strictly more capable than dumping everything, because now the model can
   find a needle at line 3,000 that a full dump would have buried anyway.

Note the shape of the win: the good tool is not a weaker version of the bad
one. It answers questions the bad one cannot.
"""

from __future__ import annotations

import re

from mcp.types import ToolAnnotations

from hr import data
from server.common import rel, table

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

MAX_TAIL = 400
MAX_MATCHES = 40


def register(mcp) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def read_paycheck_trace(paycheck_id: int, tail: int = 80) -> str:
        """Read the END of a paycheck's payroll trace, capped. Failures abort at the end, so start here.

        Returns at most `tail` lines (hard maximum 400) preceded by a header
        stating the trace's true size. Commission-heavy pay runs reach 7,000
        lines / 700k characters, so this tool NEVER returns a whole trace. To
        find something that is not in the tail, use grep_paycheck_trace.

        Args:
            paycheck_id: the paycheck id.
            tail: how many trailing lines to return. Default 80, max 400.
        """
        row = data.paycheck_by_id(paycheck_id)
        if row is None:
            return f"No paycheck {paycheck_id}."
        tail = max(1, min(tail, MAX_TAIL))
        lines = row["trace"].splitlines()
        shown = lines[-tail:]
        header = (
            f"paycheck {paycheck_id} trace: {len(lines):,} lines, "
            f"{len(row['trace']):,} chars. Showing the last {len(shown)}."
        )
        if len(lines) > len(shown):
            header += (
                f" {len(lines) - len(shown):,} earlier lines NOT shown -- "
                f"use grep_paycheck_trace(paycheck_id={paycheck_id}, pattern=...) "
                "to search them."
            )
        return header + "\n\n" + "\n".join(shown)

    @mcp.tool(annotations=READ_ONLY)
    def grep_paycheck_trace(paycheck_id: int, pattern: str, context: int = 1) -> str:
        """Search one paycheck's payroll trace for a regex and return matching lines with context.

        Use for anything not visible in read_paycheck_trace's tail. Results are
        capped at 40 matches; narrow the pattern if you hit the cap.

        Args:
            paycheck_id: the paycheck id.
            pattern: a Python regular expression, matched case-insensitively.
            context: lines of context around each match. Default 1, max 5.
        """
        row = data.paycheck_by_id(paycheck_id)
        if row is None:
            return f"No paycheck {paycheck_id}."
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Bad regex {pattern!r}: {exc}"

        context = max(0, min(context, 5))
        lines = row["trace"].splitlines()
        hits = [i for i, ln in enumerate(lines) if rx.search(ln)]
        if not hits:
            return (
                f"No match for {pattern!r} in paycheck {paycheck_id} "
                f"({len(lines):,} lines searched)."
            )

        capped = hits[:MAX_MATCHES]
        out = [f"{len(hits)} match(es) for {pattern!r} in paycheck {paycheck_id}"]
        if len(hits) > len(capped):
            out[0] += f" -- showing the first {len(capped)}, narrow the pattern for the rest"
        emitted: set[int] = set()
        for i in capped:
            for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                if j not in emitted:
                    emitted.add(j)
                    out.append(f"{j + 1:>6}: {lines[j]}")
        return "\n".join(out)

    @mcp.tool(annotations=READ_ONLY)
    def list_failed_paychecks(days: int = 30) -> str:
        """Failed paychecks in the last N days, with trace sizes so you know what you are about to read.

        Args:
            days: lookback window. Default 30.
        """
        rows = data.recent_failures(days)
        if not rows:
            return f"No payroll failures in the last {days} days."
        return table(
            ["paycheck", "employee", "period", "when", "error", "trace lines"],
            [
                [
                    r["id"],
                    r["employee_name"],
                    r["period"],
                    rel(r["issued_at"]),
                    r["error_code"],
                    f"{len(r['trace'].splitlines()):,}",
                ]
                for r in rows
            ],
        )
