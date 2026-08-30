"""Orchestrates one exhibit run and grades it.

The order of operations matters for honesty:

  reset (exhibit 5 only) -> snapshot row counts -> run -> snapshot again -> grade

Exhibit 5 resets before every run so the bad and good servers start from an
identical database. Without that, the second variant to run would inherit the
first one's damage and the scoreboard would be a lie.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from harness import llm, offline, settings
from harness.client import mcp_session
from harness.exhibits import EXHIBITS
from hr import data

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")



def model() -> str:
    """The model for the NEXT run -- read live, so the Settings tab takes effect
    without a restart."""
    return settings.current().model


def is_offline() -> bool:
    """Scripted stand-in, or the real thing?

    "auto" (the default) means: offline exactly when there is no API key. The
    Settings tab can force either way -- forcing offline is the projector-safe
    mode, and forcing live with no key produces an honest error rather than a
    silent fallback to a script that would look like a real answer.
    """
    mode = settings.current().offline
    if mode == "on":
        return True
    if mode == "off":
        return False
    return not os.environ.get("OPENAI_API_KEY")


def openai_client() -> AsyncOpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return AsyncOpenAI(api_key=key)


def _env_for_server() -> None:
    """The MCP subprocess must launch with this venv's python, from the repo root."""
    os.environ.setdefault("WHY_MCP_ROOT", str(ROOT))
    os.environ.setdefault("PYTHON_BIN", str(ROOT / ".venv" / "bin" / "python"))


async def run_exhibit(
    exhibit_id: int,
    variant: str,
    *,
    run_index: int = 0,
    context_budget: int | None = None,
    max_tool_calls: int | None = None,
    question: str | None = None,
) -> AsyncIterator[dict]:
    """Run one exhibit. `question` overrides the scripted one (the playground).

    A free-form question has no grader, and it must not have one: a substring
    check written for "why did Priya Raman's paycheck fail" says nothing about a question
    someone just invented. The verdict there is the room's, not the harness's --
    so the run yields `ok: None` and the UI shows "you judge".
    """
    ex = EXHIBITS[exhibit_id]
    _env_for_server()

    # Resolved per run, not at import: the Settings tab changes these between
    # runs and the scoreboard has to reflect what THIS run actually used.
    cfg = settings.current()
    context_budget = cfg.context_budget if context_budget is None else context_budget
    max_tool_calls = cfg.max_tool_calls if max_tool_calls is None else max_tool_calls
    model_id = cfg.model

    free_form = bool(question)
    if not free_form:
        question = ex.questions[run_index % len(ex.questions)] if ex.questions else ex.question

    # Reseed before EVERY run, not just the destructive exhibit. Exhibit 5's
    # bad server deletes rows, and anything run afterwards inherited a mangled
    # database -- diagnose_payroll_failure would report "no failures" and the exhibit
    # would fail for a reason that had nothing to do with its lesson.
    data.reset_db()
    before = data.row_counts()

    off = is_offline()
    if free_form and off:
        # The offline scripts are a fixed sequence of tool calls chosen for the
        # exhibit's own question. Replaying them against a question someone just
        # typed would look like a real answer and be pure theatre.
        yield {
            "type": "error",
            "kind": "needs_key",
            "message": (
                "Your own question needs a real model. The offline mode replays a "
                "script written for this exhibit's fixed question, so it cannot answer "
                "yours. Add OPENAI_API_KEY to .env and restart."
            ),
        }
        yield {"type": "done"}
        return

    yield {
        "type": "start", "exhibit": exhibit_id, "variant": variant, "question": question,
        "run_index": run_index, "model": "scripted (offline)" if off else model_id,
        "offline": off, "free_form": free_form,
        "context_budget": context_budget, "max_tool_calls": max_tool_calls,
    }
    yield {"type": "db", "when": "before", "counts": before}

    client = (
        offline.FakeOpenAI(offline.script_for(exhibit_id, variant, run_index))
        if off
        else openai_client()
    )
    answer, tool_names, error_kind = "", [], None
    frames: list[dict] = []

    async with mcp_session(
        variant, exhibit_id, openai_client=None if off else client, sampling_model=model_id
    ) as (session, tap):
        async for event in llm.run_conversation(
            session,
            question,
            client,
            model_id,
            max_tool_calls=max_tool_calls,
            context_budget=context_budget,
        ):
            if event["type"] == "assistant":
                answer = event["text"]
            elif event["type"] == "metrics":
                tool_names = event["tool_names"]
            elif event["type"] == "error":
                error_kind = event["kind"]
            yield event
        frames = list(tap.frames)

    after = data.row_counts()
    yield {"type": "db", "when": "after", "counts": after}

    if free_form:
        lost = (before["employees"] - after["employees"], before["paychecks"] - after["paychecks"])
        note = "no grader for your own question -- you judge"
        if any(lost):
            note = f"no grader -- but it DELETED {lost[0]} employee(s) and {lost[1]} paycheck(s)"
        yield {"type": "grade", "ok": None, "note": note}
    else:
        grade = ex.grade(answer, tool_names, before, after, error_kind)
        yield {"type": "grade", "ok": grade.ok, "note": grade.note}
    yield {"type": "wire", "frames": frames}
    yield {"type": "done"}
