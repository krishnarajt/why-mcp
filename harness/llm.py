"""The host: an OpenAI tool-calling loop over a real MCP session.

This is the smallest honest MCP client. It does exactly what Claude Code or
Cursor does -- list tools, put them in the request, execute what the model asks
for, feed results back -- and it instruments every step so the scoreboard has
real numbers instead of vibes.

Two limits exist to make failure *visible* rather than merely expensive:

  MAX_TOOL_CALLS  a runaway loop should end as a verdict, not a bill.
  CONTEXT_BUDGET  a stand-in for the context window every real client has.
                  Default 24,000 tokens. Exhibit 2's monster trace is ~236,000,
                  so it also blows a real 128k window -- the budget just makes
                  the failure instant, cheap and identical on every machine.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from mcp import types

from harness import tokens
from harness.client import tool_result_text

# A backstop, not a budget. Reasoning models explore before they act, so this
# has to be loose enough that a legitimate exploration finishes -- otherwise
# every exhibit's verdict becomes "ran out of calls" and measures nothing.
MAX_TOOL_CALLS = 20
CONTEXT_BUDGET = 24_000

SYSTEM = (
    "You are an HR and payroll assistant with access to tools over MCP. "
    "Answer the user's question using the tools available. "
    "Be concise and concrete: name the employee, the error, and the cause. "
    "When you have the answer, state it directly and stop calling tools."
)


def to_openai_tools(mcp_tools: list[types.Tool]) -> list[dict]:
    """MCP tool -> OpenAI function. This mapping is why one server works everywhere."""
    out = []
    for t in mcp_tools:
        schema = t.input_schema or {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            }
        )
    return out


async def run_conversation(
    session,
    question: str,
    openai_client,
    model: str,
    *,
    max_tool_calls: int = MAX_TOOL_CALLS,
    context_budget: int = CONTEXT_BUDGET,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one question to completion, yielding an event per step."""
    listed = await session.list_tools()
    oa_tools = to_openai_tools(listed.tools)
    schema_cost = tokens.schema_tokens(oa_tools)

    yield {
        "type": "tools",
        "count": len(oa_tools),
        "schema_tokens": schema_cost,
        "names": [t["function"]["name"] for t in oa_tools],
    }

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    calls: list[dict] = []
    prompt_tokens = completion_tokens = 0
    tool_result_tokens = 0

    hit_limit = False
    while True:
        if len(calls) >= max_tool_calls:
            hit_limit = True
            break
        used = schema_cost + tokens.messages_tokens(messages)
        if used > context_budget:
            yield {
                "type": "error",
                "kind": "context_budget",
                "message": (
                    f"Context budget exhausted before the next request: {used:,} tokens "
                    f"needed, {context_budget:,} available."
                ),
            }
            break

        resp = await openai_client.chat.completions.create(
            model=model, messages=messages, tools=oa_tools or None, tool_choice="auto"
        )
        if resp.usage:
            prompt_tokens += resp.usage.prompt_tokens
            completion_tokens += resp.usage.completion_tokens
        choice = resp.choices[0].message

        if not choice.tool_calls:
            yield {"type": "assistant", "text": choice.content or ""}
            messages.append({"role": "assistant", "content": choice.content or ""})
            break

        messages.append(
            {
                "role": "assistant",
                "content": choice.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.tool_calls
                ],
            }
        )

        blew_budget = False
        for tc in choice.tool_calls:
            # A turn can carry several parallel tool_calls; the cap is on calls.
            if len(calls) >= max_tool_calls:
                hit_limit = True
                break
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_call", "n": len(calls) + 1, "name": tc.function.name, "args": args}

            try:
                result = await session.call_tool(tc.function.name, args)
                text = tool_result_text(result)
                is_error = bool(getattr(result, "is_error", False))
            except Exception as exc:
                text, is_error = f"Tool error: {exc}", True

            cost = tokens.count(text)
            tool_result_tokens += cost
            calls.append({"name": tc.function.name, "args": args, "tokens": cost})
            yield {
                "type": "tool_result",
                "n": len(calls),
                "name": tc.function.name,
                "chars": len(text),
                "tokens": cost,
                "is_error": is_error,
                "preview": text[:600],
            }

            # The teaching moment: name the tool, its size, and the budget.
            if cost > context_budget:
                yield {
                    "type": "error",
                    "kind": "context_budget",
                    "message": (
                        f"{tc.function.name} returned {cost:,} tokens in ONE call. "
                        f"The context budget is {context_budget:,}. This result cannot be "
                        f"put in the conversation at all -- and at {cost:,} tokens it would "
                        f"also overflow a real 128k window."
                    ),
                }
                blew_budget = True
                break

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

        if blew_budget or hit_limit:
            break

    if hit_limit:
        yield {
            "type": "error",
            "kind": "tool_call_limit",
            "message": (
                f"Stopped after {len(calls)} tool calls without reaching an answer "
                f"(cap {max_tool_calls}). A model that needs this many calls to answer "
                f"one question is telling you something about the tool surface."
            ),
        }

    yield {
        "type": "metrics",
        "tool_calls": len(calls),
        "tool_names": [c["name"] for c in calls],
        "schema_tokens": schema_cost,
        "tool_result_tokens": tool_result_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
