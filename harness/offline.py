"""Offline mode: a scripted stand-in for the model.

Set WHY_MCP_OFFLINE=1 and every exhibit runs with no API key and no network,
following a fixed script of tool calls. Two reasons this exists:

1. PROJECTOR SAFETY. Live model calls are non-deterministic, and a demo that
   depends on the network is a demo that dies in a conference room. Run offline
   for the walkthrough, then hit the same exhibit live for the reveal.

2. IT IS A TEST. `evals/selftest.py` uses these same scripts to check the
   transport, the token accounting, the budget abort and every grader without
   spending a cent. If the self-test passes, the only thing left that can
   surprise you is the model -- which is exhibit 7's entire point.

The scripts are what a plausible gpt-4o-mini actually does against each server.
They are not the real thing and the UI says so.
"""

from __future__ import annotations

import json
import types as pytypes
from dataclasses import dataclass, field


@dataclass
class Script:
    """Steps are ('call', tool_name, args) or ('say', text)."""

    steps: list[tuple]
    i: int = 0

    def next_message(self):
        step = self.steps[min(self.i, len(self.steps) - 1)]
        self.i += 1
        if step[0] == "call":
            tc = pytypes.SimpleNamespace(
                id=f"call_{self.i}",
                function=pytypes.SimpleNamespace(name=step[1], arguments=json.dumps(step[2])),
            )
            return pytypes.SimpleNamespace(content=None, tool_calls=[tc])
        return pytypes.SimpleNamespace(content=step[1], tool_calls=None)


@dataclass
class FakeOpenAI:
    """Quacks like AsyncOpenAI.chat.completions for our loop's purposes."""

    script: Script
    chat: object = field(init=False)

    def __post_init__(self) -> None:
        self.chat = pytypes.SimpleNamespace(completions=self)

    async def create(self, **_kw):
        msg = self.script.next_message()
        return pytypes.SimpleNamespace(
            choices=[pytypes.SimpleNamespace(message=msg)],
            usage=pytypes.SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


SCRIPTS: dict[tuple[int, str], list[tuple]] = {
    (1, "bad"): [
        ("call", "list_employees", {}),
        ("call", "list_paychecks", {"employee_id": 1, "limit": 5}),
        ("call", "get_paycheck", {"paycheck_id": 9001}),
        ("call", "get_paycheck_trace", {"paycheck_id": 9001}),
        ("call", "list_org_changes", {"limit": 5}),
        ("say", "Priya Raman's paycheck failed because cost center CC-4100 ran out of budget."),
    ],
    (1, "good"): [
        ("call", "diagnose_payroll_failure", {"employee_name": "Priya Raman"}),
        ("say", "Cost center budget exceeded on CC-4100 (200,000 committed against a 200,000 "
                "ceiling). Reorg 4.2 moved the Platform team into CC-4100 two hours before the "
                "payroll close and did not request a budget change -- the same cause as a SEV2 "
                "14 months ago."),
    ],
    (2, "bad"): [
        ("call", "get_paycheck_trace", {"paycheck_id": 9002}),
        # Normally unreachable: the 236k-token result aborts the run first. It
        # BECOMES reachable if you raise the context budget past the trace size
        # in the Settings tab, so this has to be a plausible wrong answer rather
        # than a placeholder -- and vague-but-confident is exactly what 236,000
        # tokens of noise buys you.
        (
            "say",
            "Marcus Bell's pay run aborted partway through commission pricing. The trace "
            "shows repeated retries and the run shutting down with deals still unpriced.",
        ),
    ],
    (2, "good"): [
        ("call", "read_paycheck_trace", {"paycheck_id": 9002, "tail": 80}),
        ("say", "FATAL: the commission engine rejected the run -- rate table SALES-EMEA-2026H2 "
                "is not published for territory EMEA-3. 8,123 deals were left unpriced."),
    ],
    (3, "bad"): [
        ("call", "search", {"q": "cost center budget exceeded"}),
        ("say", "Yes -- Priya Raman hit 'cost center budget exceeded' on paycheck 9001 last cycle."),
    ],
    (3, "good"): [
        ("call", "search_hr_cases", {"query": "cost center budget"}),
        ("say", "Yes. A SEV2 14 months ago: a team was moved into CC-4100 without raising its "
                "200,000 budget. The fix was a 500,000 ceiling plus a pre-flight capacity check. "
                "The action item to alert above 80% was never completed."),
    ],
    (4, "bad"): [
        ("call", "get_all_employee_payroll_stats", {}),
        ("say", "Wei Zhang looks like the problem here."),
    ],
    (4, "good"): [
        ("call", "payroll_health_report", {}),
        ("say", "Marcus Bell is worst -- BLOCKED at 7% over 12 months. Wei Zhang is UNSTABLE at "
                "50%. Priya Raman failed her last cycle."),
    ],
    (5, "bad"): [
        ("call", "list_employees_brief", {}),
        ("call", "run_sql", {"query": "DELETE FROM paychecks WHERE status = 'failed'"}),
        ("say", "Cleaned up: I removed the failed paycheck records so finance stops escalating."),
    ],
    (5, "good"): [
        ("call", "list_employees_brief", {}),
        ("call", "hold_payroll", {"employee_name": "Marcus Bell"}),
        ("say", "Put Marcus Bell's payroll on hold so the runs stop failing. Nothing was deleted "
                "-- release the hold once the EMEA-3 rate table is published."),
    ],
    (6, "bad"): [
        ("call", "get_settings", {}),
        ("call", "get_config", {}),
        ("call", "describe_schema", {}),
        ("say", "All payroll timestamps are UTC."),
    ],
    (6, "good"): [
        ("call", "describe_schema", {}),
        ("say", "All payroll timestamps are UTC, and pay periods are evaluated in UTC too."),
    ],
}

# Exhibit 7 varies by paraphrase, not by variant: the runs that hand the tool a
# name it cannot match are the ones that fail. Three of ten, deterministically --
# and every one of those three is a way a human would really write a colleague's
# name.
E7_MISSES = {2, 4, 7}
E7_WRONG_NAMES = {2: "deniz okonkwo", 4: "D. Okonkwo", 7: "Okonkwo"}


def script_for(exhibit: int, variant: str, run_index: int) -> Script:
    if exhibit == 7:
        i = run_index % 10
        if i in E7_MISSES:
            return Script(
                [
                    ("call", "employee_payroll_health", {"employee_name": E7_WRONG_NAMES[i]}),
                    ("say", "I could not find an employee by that name."),
                ]
            )
        return Script(
            [
                ("call", "employee_payroll_health", {"employee_name": "Deniz Okonkwo"}),
                ("say", "Deniz Okonkwo's payroll is healthy -- 93% success over the last "
                        "12 months."),
            ]
        )
    return Script(list(SCRIPTS[(exhibit, variant)]))
