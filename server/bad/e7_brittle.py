"""EXHIBIT 7 -- the tool that looks perfect. NO FIX SHIPS. ⚠️ SPOILER-LIGHT

DESIGN CHOICE: none, deliberately. This file is byte-identical in intent on the
good server (`server/good/e7_brittle.py` imports it). There is no bad version
and no good version, because the point of exhibit 7 is that you cannot tell.

`employee_payroll_health` is well named, has a real description, is read-only,
returns a compact table, and takes exactly one obvious argument. It passes every
review in this repo. Then you ask it the same question ten different ways --
"is Deniz Okonkwo's payroll ok?", "how's Deniz doing?", "check Okonkwo" -- and
it answers seven of them.

Human names are where this bites hardest in real life. Nobody types a full
legal name the same way twice, and an exact-match lookup on `employee_name`
turns every variation into "that person does not exist".

Do NOT fix this. The lesson is not a patch, it is a practice: without an eval
harness that runs N paraphrases and reports a pass rate, you have no idea which
of your tools is the 7/10 one. See PITFALLS.md for what the fix would be, and
why applying it would delete the exhibit.
"""

from __future__ import annotations

from hr import data
from server.common import rel, table, verdict


def register(mcp) -> None:
    @mcp.tool()
    def employee_payroll_health(employee_name: str) -> str:
        """Payroll health for one employee: last paycheck, 12-month success rate, verdict.

        Args:
            employee_name: the employee's name.
        """
        emp = data.employee_by_name(employee_name)
        if emp is None:
            return f"No employee named {employee_name!r}."
        stats = data.payroll_stats(emp["id"])
        checks = data.paychecks_for_employee(emp["id"], limit=1)
        last = checks[0] if checks else None
        return table(
            ["employee", "last paycheck", "status", f"{data.STATS_LABEL} success", "verdict"],
            [
                [
                    emp["name"],
                    rel(last["issued_at"]) if last else "never",
                    last["status"] if last else "-",
                    f"{stats['rate']:.0%} ({stats['paid']}/{stats['total']})",
                    verdict(stats["rate"], last["status"] if last else "-"),
                ]
            ],
        )
