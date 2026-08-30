"""EXHIBIT 3 (good) -- the description does the disambiguating.

DESIGN CHOICE: treat every tool description as prompt engineering, because that
is exactly what it is. The model chooses between your tools using nothing but
the name, the description, and the argument names. That text is the only
control surface you have over tool choice.

Same two tools as the bad server. Same queries. Same data. The only change is
the words -- and the words follow a formula:

  WHAT it covers       "payroll traces, last 12 months only"
  WHEN to reach for it "use for 'whose pay is failing right now'"
  WHAT IT DOES NOT     "does NOT contain anything older than 12 months"
  WHERE TO GO INSTEAD  "for prior art, use search_hr_cases"

That last line is the one everybody skips and the one that does the most work.
A tool that names its sibling makes the wrong choice self-correcting; a tool
that stays silent about its boundaries makes the wrong choice invisible.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from hr import data
from server.common import rel, table

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def register(mcp) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def search_pay_traces(pattern: str) -> str:
        """Full-text search across payroll engine traces from the LAST 12 MONTHS ONLY.

        Use this for "whose pay is failing right now" / "which employee is
        hitting this error this cycle". Returns matching paychecks, not trace
        bodies -- follow up with read_paycheck_trace or grep_paycheck_trace.

        Traces are purged after 12 months, so this index cannot answer "has
        this happened before" or "have we seen this in the past". For
        historical precedent, use search_hr_cases instead.

        Args:
            pattern: substring to look for, case-insensitive.
        """
        rows = data.search_traces(pattern)
        if not rows:
            return (
                f"No payroll trace in the last 12 months contains {pattern!r}. "
                "If you are looking for historical precedent, try search_hr_cases."
            )
        return table(
            ["paycheck", "employee", "period", "when", "status"],
            [
                [r["id"], r["employee_name"], r["period"], rel(r["issued_at"]), r["status"]]
                for r in rows
            ],
        )

    @mcp.tool(annotations=READ_ONLY)
    def search_hr_cases(query: str) -> str:
        """Full-text search over CLOSED HR CASE FILES going back several years.

        This is the historical record: use it for "has this happened before",
        "is there prior art", "what did we do last time", root-cause research,
        and finding action items that were never completed.

        It does NOT contain live or recent payroll traces -- a case only appears
        here after it was closed and written up. For what is failing this cycle,
        use search_pay_traces instead.

        Args:
            query: substring matched against case titles and resolution text.
        """
        rows = data.search_hr_cases(query)
        if not rows:
            return (
                f"No closed HR case mentions {query!r}. "
                "If you meant a live payroll failure, try search_pay_traces."
            )
        out = []
        for case in rows:
            out.append(f"[{case['severity']}] {case['title']} -- opened {rel(case['opened_at'])}")
            out.append(f"  {case['resolution']}")
            out.append("")
        return "\n".join(out)
