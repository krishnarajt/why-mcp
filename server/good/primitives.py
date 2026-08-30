"""THE PRIMITIVES TOUR -- tools are one quarter of MCP.

Registered on the good server only, and exercised from the "Primitives" tab
rather than by the exhibit scoreboard. Each one exists so you can watch the
actual JSON-RPC frames it produces in the wire inspector.

  TOOL        model-decided action.                   tools/list, tools/call
  RESOURCE    user/app-attached context, by URI.      resources/list, resources/read
              NOT a tool call -- the client fetches it and puts it in context,
              so the model never spends a turn deciding to.
  PROMPT      user-invoked template.                  prompts/list, prompts/get
              This is what becomes a slash command in a client.
  SAMPLING    the SERVER asks the CLIENT's model.     sampling/createMessage
              Inverted control flow: your server gets an LLM without an API
              key, billed to whoever is using it.
  ELICITATION the SERVER asks the USER a question.    elicitation/create
              The protocol-native confirmation. Client support is uneven,
              which is why exhibit 5 also uses a confirm token.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from hr import data
from server.common import error_lines, rel


def register(mcp) -> None:
    # ---------------- RESOURCES ----------------

    @mcp.resource(
        "hr://employees",
        name="Employee directory",
        description="Every employee with their title, department and payroll state.",
        mime_type="text/markdown",
    )
    def employees_resource() -> str:
        lines = ["# Employees", ""]
        depts = {d["id"]: d["name"] for d in data.q("SELECT * FROM departments")}
        for emp in data.all_employees():
            state = "ON HOLD" if emp["payroll_hold"] else "payroll active"
            lines.append(
                f"- **{emp['name']}** — {emp['title']}, {depts[emp['department_id']]} ({state})"
            )
        return "\n".join(lines)

    @mcp.resource(
        "hr://paycheck/{paycheck_id}/trace",
        name="Payroll trace tail",
        description="The last 60 lines of one paycheck's payroll trace. A resource "
        "template: the client fills in paycheck_id, so nothing is fetched until "
        "someone asks.",
        mime_type="text/plain",
    )
    def paycheck_trace_resource(paycheck_id: str) -> str:
        row = data.paycheck_by_id(int(paycheck_id))
        if row is None:
            return f"No paycheck {paycheck_id}."
        lines = row["trace"].splitlines()
        return (
            f"# paycheck {paycheck_id} -- last 60 of {len(lines):,} lines\n\n"
            + "\n".join(lines[-60:])
        )

    # ---------------- PROMPTS ----------------

    @mcp.prompt(
        name="payroll_triage",
        title="Triage failed paychecks",
        description="Walk the payroll triage checklist for the last N days.",
    )
    def payroll_triage_prompt(days: str = "30") -> str:
        return (
            f"You are the payroll analyst on duty. Triage every failed paycheck in the "
            f"last {days} days.\n\n"
            "For each failure, in this order:\n"
            "1. Call recent_payroll_failures to get the list.\n"
            "2. Call diagnose_payroll_failure for each affected employee.\n"
            "3. Check whether an org change in the preceding window is the likely cause.\n"
            "4. Check search_hr_cases for prior art and for action items never completed.\n"
            "5. Recommend hold_payroll only if the pay run is failing repeatedly and the "
            "employee has been made whole another way.\n\n"
            "Finish with a table: employee | root cause | confidence | recommended action."
        )

    @mcp.prompt(
        name="case_writeup",
        title="Draft an HR case file",
        description="Draft a case-file skeleton for one failed paycheck.",
    )
    def case_writeup_prompt(paycheck_id: str) -> str:
        row = data.paycheck_by_id(int(paycheck_id))
        if row is None:
            return f"No paycheck {paycheck_id}."
        errs = "\n".join(error_lines(row["trace"], 4))
        return (
            f"Draft an HR case file for paycheck {paycheck_id} "
            f"({rel(row['issued_at'])}, period {row['period']}, error "
            f"{row['error_code']}).\n\nError lines:\n{errs}\n\n"
            "Sections: Who was affected, Timeline, Root cause, What went well, Action "
            "items (each with an owner). Be specific; do not invent times or amounts."
        )

    # ---------------- SAMPLING (server -> client's model) ----------------

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    async def summarise_case(case_id: int, ctx: Context) -> str:
        """Summarise a closed HR case file in one sentence, using the CLIENT's model.

        Demonstrates SAMPLING: this server has no API key and no model of its
        own. It calls back into the client with sampling/createMessage and the
        client's model does the work. Watch the wire inspector -- you will see a
        request travelling server -> client, the opposite direction from every
        other frame.

        Args:
            case_id: the HR case id.
        """
        rows = data.q("SELECT * FROM hr_cases WHERE id = ?", (case_id,))
        if not rows:
            return f"No HR case {case_id}."
        case = rows[0]
        result = await ctx.session.create_message(
            messages=[
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": f"In ONE sentence, state the root cause and the fix:\n\n"
                        f"{case['title']}\n{case['resolution']}",
                    },
                }
            ],
            max_tokens=120,
            system_prompt="You write terse, factual HR case summaries.",
        )
        text = getattr(result.content, "text", str(result.content))
        return f"(summarised by the client's model, {result.model})\n\n{text}"

    # ---------------- ELICITATION (server -> user) ----------------

    class BudgetChange(BaseModel):
        limit_usd: int = Field(description="New monthly payroll ceiling for CC-4100, in USD.")
        reason: str = Field(default="", description="Why, for the audit log.")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
    async def change_cost_center_budget(ctx: Context) -> str:
        """Change a cost center's payroll budget -- asks the USER for the value it needs.

        Demonstrates ELICITATION: the tool is called with no arguments and stops
        mid-execution to ask a human, with a schema describing what it wants.
        Contrast exhibit 5's confirm-token pattern, which achieves a similar
        guarantee without needing the client to implement elicitation at all.
        """
        result = await ctx.elicit(
            "A cost-center move against an unchanged budget caused a SEV2 before "
            "(case 1). What monthly payroll ceiling should CC-4100 have?",
            schema=BudgetChange,
        )
        if result.action != "accept" or result.data is None:
            return f"Cancelled by the user (action={result.action}). Nothing changed."
        return (
            f"Would set the CC-4100 monthly payroll ceiling to "
            f"{result.data.limit_usd:,} USD "
            f"(reason: {result.data.reason or 'none given'}). "
            "Demo server -- nothing was actually written."
        )
