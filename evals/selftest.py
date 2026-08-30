"""Keyless smoke test: proves the plumbing without spending a cent.

Substitutes a scripted stand-in for the model that calls a fixed sequence of
tools and then answers. That exercises everything except the model's judgement:
stdio transport, tools/list, tools/call, the wire tap, token accounting, the
context-budget abort, and every grader.

Run it before a talk. If this passes, the only thing that can still surprise
you on stage is the model -- which is exhibit 7's entire point.

    uv run python -m evals.selftest
"""

from __future__ import annotations

import asyncio

from harness import llm
from harness.client import mcp_session
from harness.exhibits import EXHIBITS
from harness.offline import FakeOpenAI, script_for
from harness.runner import _env_for_server
from hr import data

BAD_SHOULD_FAIL = {2, 3, 4, 5}


async def run_one(exhibit_id: int, variant: str, run_index: int = 0) -> dict:
    ex = EXHIBITS[exhibit_id]
    data.reset_db()          # same rule as the runner: every run starts clean
    before = data.row_counts()

    fake = FakeOpenAI(script_for(exhibit_id, variant, run_index))
    question = ex.questions[run_index % len(ex.questions)] if ex.questions else ex.question
    answer, tool_names, error_kind, metrics = "", [], None, {}

    async with mcp_session(variant, exhibit_id) as (session, tap):
        async for ev in llm.run_conversation(session, question, fake, "scripted"):
            if ev["type"] == "assistant":
                answer = ev["text"]
            elif ev["type"] == "metrics":
                metrics, tool_names = ev, ev["tool_names"]
            elif ev["type"] == "error":
                error_kind = ev["kind"]
        frames = len(tap.frames)

    grade = ex.grade(answer, tool_names, before, data.row_counts(), error_kind)
    return {
        "calls": metrics.get("tool_calls", 0),
        "schema": metrics.get("schema_tokens", 0),
        "results": metrics.get("tool_result_tokens", 0),
        "frames": frames,
        "ok": grade.ok,
        "note": grade.note,
    }


async def main() -> None:
    _env_for_server()
    data.reset_db()
    print(f"{'exhibit':<34} {'variant':<7} {'calls':>5} {'schema':>7} {'results':>8} "
          f"{'frames':>6}  verdict")
    print("-" * 106)
    failures = 0
    for eid, ex in EXHIBITS.items():
        for variant in (("bad", "good") if ex.paired else ("bad",)):
            if eid == 7:  # the whole point is the pass RATE, so run all ten
                results = [await run_one(eid, variant, i) for i in range(10)]
                passes = sum(1 for r in results if r["ok"])
                r = results[0]
                verdict = f"{passes}/10 paraphrases answered"
                if passes in (0, 10):
                    failures += 1
                    verdict += "  ^ expected a MIXED rate"
            else:
                r = await run_one(eid, variant)
                expected = not (variant == "bad" and eid in BAD_SHOULD_FAIL)
                verdict = ("PASS" if r["ok"] else "FAIL") + "  " + r["note"]
                if r["ok"] != expected:
                    failures += 1
                    verdict += f"  ^ wanted {'PASS' if expected else 'FAIL'}"
            print(f"{f'{eid}. {ex.title}':<34} {variant:<7} {r['calls']:>5} {r['schema']:>7,} "
                  f"{r['results']:>8,} {r['frames']:>6}  {verdict}")
        print()
    data.reset_db()
    print("plumbing OK" if failures == 0 else f"{failures} unexpected verdict(s)")


if __name__ == "__main__":
    asyncio.run(main())
