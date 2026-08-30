"""Payroll-engine trace generators for the seeded HR database.

Exhibit 2 lives or dies on one number: a commission-heavy pay run emits ~600k
characters of calculation trace. That is deliberately larger than any sane
context window, so the bad server's "return the whole trace" tool cannot
possibly work.
"""

from __future__ import annotations

import random

# The buried root cause for the exhibit-2 monster trace.
RATE_TABLE_FATAL = (
    "FATAL: commission engine rejected the run: rate table SALES-EMEA-2026H2 "
    "is not published for territory EMEA-3"
)

NOISE = [
    "priced deal {n} at {ms}bps (plan=SALES-2026H2 tier={p})",
    "accrual batch {n} accepted (currency=USD fx_locked=true)",
    "checkpoint deal_id={n} territory=EMEA-{p} carry={ms}",
    "quota attainment recalculated for rep segment {p} in {ms}ms",
    "GET /api/comp/plans/{n} 200 {ms}ms",
    "rotated accrual ledger segment {n} (rows=64000)",
    "clawback window closed for deal {n}, {p} adjustments applied",
    "WARN retry {p}/5 pricing deal {n}: RateTableLockedTemporarily",
    "released {p} idle pricing workers",
    "ledger reconciliation completed in {ms}ms",
]


def _noise_line(rnd: random.Random, i: int) -> str:
    tpl = NOISE[i % len(NOISE)]
    body = tpl.format(n=rnd.randint(1000, 999999), p=rnd.randint(0, 9), ms=rnd.randint(1, 900))
    return (
        f"2026-08-26T04:{i // 60 % 60:02d}:{i % 60:02d}.{rnd.randint(0, 999):03d}Z "
        f"INFO  commission-engine {body}"
    )


def monster_trace(rnd: random.Random, lines: int = 7000) -> str:
    """~600k chars of plausible commission math with a FATAL on the final line.

    The tail is where the answer is, which is exactly why `tail=80` works and
    "return everything" does not.
    """
    out = [_noise_line(rnd, i) for i in range(lines - 6)]
    out += [
        "2026-08-26T04:59:54.101Z WARN  commission-engine territory EMEA-3 resolved to plan SALES-EMEA-2026H2",
        "2026-08-26T04:59:55.204Z INFO  commission-engine loading rate table SALES-EMEA-2026H2",
        "2026-08-26T04:59:56.377Z WARN  commission-engine rate table lookup returned status=DRAFT",
        "2026-08-26T04:59:57.480Z INFO  commission-engine retrying rate table load (attempt 3/3)",
        f"2026-08-26T04:59:58.912Z ERROR commission-engine {RATE_TABLE_FATAL}",
        "2026-08-26T04:59:59.001Z INFO  commission-engine aborting pay run, 8123 deals unpriced",
    ]
    return "\n".join(out)


BUDGET_FAIL_TRACE = """\
2026-08-26T02:00:01.004Z INFO  payroll starting gross-to-net, cost center CC-4100
2026-08-26T02:00:01.198Z INFO  payroll payroll-engine reports version 4.2.0
2026-08-26T02:00:01.402Z INFO  payroll budget policy: monthly ceiling 200,000 USD on CC-4100
2026-08-26T02:00:02.115Z INFO  payroll enumerating components: base, equity refresh, shift premium
2026-08-26T02:03:44.881Z INFO  payroll base pay computed (8,541.66 USD)
2026-08-26T02:11:09.240Z INFO  payroll pre-tax deductions applied (1,204.10 USD)
2026-08-26T02:11:09.441Z INFO  payroll committing to cost center CC-4100 (est. 9,745.76 USD)
2026-08-26T02:19:52.677Z WARN  payroll CC-4100 at 96% of its monthly budget
2026-08-26T02:21:03.109Z WARN  payroll commit stalled 11s waiting on the budget ledger
2026-08-26T02:22:41.556Z ERROR payroll commit failed: BUDGET_EXHAUSTED
2026-08-26T02:22:41.557Z ERROR payroll cost center budget exceeded on CC-4100 (limit 200,000, committed 200,000)
2026-08-26T02:22:41.902Z ERROR payroll rolling back partial paycheck for employee 1
2026-08-26T02:22:43.010Z INFO  payroll exit code 28
"""

PAYRUN_OK_TRACE = """\
{date}T02:00:01.004Z INFO  payroll starting gross-to-net, cost center CC-4100
{date}T02:00:01.402Z INFO  payroll budget policy: monthly ceiling 500,000 USD on CC-4100
{date}T02:14:22.118Z INFO  payroll all components computed (net 9,745.76 USD)
{date}T02:14:22.640Z INFO  payroll committed to CC-4100, cost center at 61% of budget
{date}T02:14:22.910Z INFO  payroll exit code 0
"""

RETRO_FAIL_TRACE = """\
2026-08-26T03:30:00.881Z INFO  payroll applying 41 retro adjustments for the prior period
2026-08-26T03:31:14.002Z WARN  payroll period lock wait 30s on 2026-07-B
2026-08-26T03:31:44.118Z ERROR payroll deadlock detected against the ledger export, transaction rolled back
2026-08-26T03:31:44.220Z INFO  payroll exit code 1
"""

GENERIC_OK_TRACE = """\
INFO  payroll starting gross-to-net for {name}
INFO  payroll processed {n} pay components in {ms}ms
INFO  payroll exit code 0
"""
