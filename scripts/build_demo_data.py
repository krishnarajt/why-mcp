"""Bake the static demo site's fixtures out of the real servers.

    uv run python scripts/build_demo_data.py

Writes `demo-site/demo-data.js`. Everything in that file is *captured*, not
written by hand: the tool outputs come from spawning the real MCP servers over
stdio and calling the real tools, the run traces come from the real harness in
offline mode, and the code snippets are extracted from the real source with the
same `ast` walk the live app uses at request time.

That is the whole point. A static teaching site that quotes made-up numbers is
worse than no site, because nobody can tell. Re-run this after changing a
server and the demo site follows.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["WHY_MCP_ROOT"] = str(ROOT)
os.environ.setdefault("PYTHON_BIN", str(ROOT / ".venv" / "bin" / "python"))
# The capture must never make a network call: the fixtures have to be identical
# on every machine, and a live model would make them a snapshot of one afternoon.
os.environ.pop("OPENAI_API_KEY", None)

from app.main import PRESETS, SOURCE_ALLOWLIST, _find_symbol  # noqa: E402
from harness import settings, tokens  # noqa: E402
from harness.client import mcp_session, tool_result_text  # noqa: E402
from harness.exhibits import EXHIBITS  # noqa: E402
from harness.lessons import LESSONS, PRIMER, PRIMITIVES  # noqa: E402
from harness.llm import to_openai_tools  # noqa: E402
from harness.offline import SCRIPTS  # noqa: E402
from hr import data  # noqa: E402

settings.update({"offline": "on"})

OUT_FILE = ROOT / "demo-site" / "demo-data.js"

# Exhibit 4's 57k-char dump IS the lesson -- you are meant to scroll it. Exhibit
# 2's 700k-char trace is not; its lesson is that it does not fit anywhere, and
# shipping it would make the demo site heavier than the thing it criticises.
MAX_EMBED_CHARS = 70_000


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# 1. run every exhibit through the real harness
# ---------------------------------------------------------------------------


async def capture_runs() -> dict:
    from harness import runner

    out: dict[str, list] = {}
    for ex_id, ex in EXHIBITS.items():
        for variant in (["bad", "good"] if ex.paired else ["bad"]):
            key = f"{ex_id}:{variant}"
            out[key] = []
            for i in range(ex.default_runs):
                events = []
                async for e in runner.run_exhibit(ex_id, variant, run_index=i):
                    if e["type"] == "wire":
                        continue  # captured once, separately, in full
                    if e["type"] == "tool_result":
                        e = {**e, "preview": (e.get("preview") or "")[:600]}
                    events.append(e)
                out[key].append(events)
            log(f"  runs {key}: {ex.default_runs} x {len(out[key][0])} events")
    return out


# ---------------------------------------------------------------------------
# 2. call every tool the site needs to show, on the real servers
# ---------------------------------------------------------------------------


def wanted_calls() -> dict[tuple, dict]:
    """Every (exhibit, variant, tool, args) the demo site can render."""
    want: dict[tuple, dict] = {}

    def add(ex: int, variant: str, tool: str, args: dict) -> None:
        want[(ex, variant, tool, json.dumps(args, sort_keys=True))] = args

    for lesson in LESSONS.values():
        for d in lesson.demos:
            add(d.exhibit, d.variant, d.tool, d.args)
    for (ex, variant), steps in SCRIPTS.items():
        for step in steps:
            if step[0] == "call":
                add(ex, variant, step[1], step[2])

    # Extras the static site needs that no script or demo happens to cover.
    add(3, "bad", "find", {"q": "cost center budget exceeded"})   # the other coin face
    add(5, "bad", "run_sql", {"query": "DELETE FROM paychecks WHERE status = 'failed'"})
    add(7, "bad", "employee_payroll_health", {"employee_name": "Deniz Okonkwo"})
    for miss in ("Okonkwo", "deniz okonkwo", "D. Okonkwo"):
        add(7, "bad", "employee_payroll_health", {"employee_name": miss})
    return want


async def capture_tools() -> tuple[dict, dict]:
    groups: dict[tuple[int, str], list] = {}
    for (ex, variant, tool, akey), args in wanted_calls().items():
        groups.setdefault((ex, variant), []).append((tool, args, akey))

    surfaces, calls = {}, {}
    for (ex, variant), items in sorted(groups.items()):
        data.reset_db()  # exhibit 5's bad run_sql really does delete rows
        async with mcp_session(variant, ex) as (session, _tap):
            listed = await session.list_tools()
            surfaces[f"{ex}:{variant}"] = {
                "count": len(listed.tools),
                "schema_tokens": tokens.schema_tokens(to_openai_tools(listed.tools)),
                "tools": [
                    {"name": t.name, "description": t.description or "",
                     "schema": t.input_schema or {}}
                    for t in listed.tools
                ],
            }
            for tool, args, akey in items:
                try:
                    text = tool_result_text(await session.call_tool(tool, args))
                except Exception as exc:  # a broken fixture must be visible, not silent
                    text = f"CAPTURE ERROR: {type(exc).__name__}: {exc}"
                chars, toks, elided = len(text), tokens.count(text), 0
                if chars > MAX_EMBED_CHARS:
                    lines = text.splitlines()
                    elided = len(lines) - 120
                    text = (
                        "\n".join(lines[:60])
                        + f"\n\n… {elided:,} lines elided in this static demo — "
                        f"the real result is {chars:,} chars …\n\n"
                        + "\n".join(lines[-60:])
                    )
                calls[f"{ex}:{variant}:{tool}:{akey}"] = {
                    "exhibit": ex, "variant": variant, "tool": tool, "args": args,
                    "text": text, "chars": chars, "tokens": toks, "elided": elided,
                }
        log(f"  tools {ex}:{variant}: {surfaces[f'{ex}:{variant}']['count']} tools, "
            f"{len(items)} calls")
    data.reset_db()
    return surfaces, calls


# ---------------------------------------------------------------------------
# 3. the primitives tour, and a real wire trace
# ---------------------------------------------------------------------------


async def capture_primitives() -> tuple[dict, dict]:
    prim: dict[str, dict] = {}
    async with mcp_session("good", 0) as (session, tap):
        def frames() -> list:
            f = list(tap.frames)
            tap.frames.clear()
            return f

        frames()  # discard the initialize handshake

        listed = await session.list_tools()
        prim["tools"] = {
            "result": "\n".join(
                f"{t.name}({', '.join((t.input_schema or {}).get('properties', {}))})"
                f"\n    {(t.description or '').splitlines()[0] if t.description else ''}"
                for t in listed.tools
            ),
            "frames": frames(),
        }

        res = await session.list_resources()
        tpl = await session.list_resource_templates()
        prim["resources"] = {
            "result": "\n".join(
                [f"{r.uri}  -- {r.name}" for r in res.resources]
                + [f"{t.uri_template}  -- {t.name} (template)" for t in tpl.resource_templates]
            ),
            "frames": frames(),
        }

        read = await session.read_resource("hr://employees")
        prim["read_resource"] = {"result": read.contents[0].text[:2500], "frames": frames()}

        prompts = await session.list_prompts()
        prim["prompts"] = {
            "result": "\n".join(f"/{p.name}  -- {p.description}" for p in prompts.prompts),
            "frames": frames(),
        }

        got = await session.get_prompt("payroll_triage", {"days": "30"})
        prim["get_prompt"] = {
            "result": "\n\n".join(getattr(m.content, "text", "") for m in got.messages),
            "frames": frames(),
        }

        # Elicitation works with no API key at all -- the client answers it, not a
        # model -- which is exactly why it is the one worth baking in. Sampling
        # needs a real completion, so the static site explains it instead.
        elicit = await session.call_tool("change_cost_center_budget", {})
        prim["elicitation"] = {"result": tool_result_text(elicit), "frames": frames()}

    wire = {}
    for variant in ("bad", "good"):
        async with mcp_session(variant, 1) as (session, tap):
            await session.list_tools()
            if variant == "good":
                await session.call_tool("diagnose_payroll_failure", {"employee_name": "Priya Raman"})
            else:
                await session.call_tool("list_employees", {})
                await session.call_tool("get_paycheck", {"paycheck_id": 9001})
            wire[f"1:{variant}"] = tap.frames
    log(f"  primitives: {len(prim)} actions; wire: {len(wire)} traces")
    return prim, wire


# ---------------------------------------------------------------------------
# 4. source + snippets, extracted the same way the live app does it
# ---------------------------------------------------------------------------


def capture_source() -> tuple[dict, dict]:
    sources = {
        path: (ROOT / path).read_text()
        for path in sorted(SOURCE_ALLOWLIST)
        if (ROOT / path).is_file()
    }
    wanted = {(s.path, s.symbol) for lesson in LESSONS.values() for s in lesson.snippets}
    wanted |= {(s["path"], s["symbol"]) for s in PRIMITIVES["snippets"]}

    snippets = {}
    for path, symbol in sorted(wanted):
        src = sources.get(path)
        if src is None:
            log(f"  !! {path} is not in SOURCE_ALLOWLIST"); continue
        found = _find_symbol(ast.parse(src), symbol)
        if found is None:
            log(f"  !! no symbol {symbol!r} in {path}"); continue
        start, end = found
        snippets[f"{path}::{symbol}"] = {
            "path": path, "symbol": symbol, "start_line": start, "end_line": end,
            "code": textwrap.dedent("\n".join(src.splitlines()[start - 1 : end])),
        }
    log(f"  source: {len(sources)} files, {len(snippets)} snippets")
    return sources, snippets


# ---------------------------------------------------------------------------


def lesson_json(lesson) -> dict:
    return {
        "headline": lesson.headline,
        "what_happens": lesson.what_happens,
        "why_tempting": lesson.why_tempting,
        "what_it_costs": lesson.what_it_costs,
        "rule": lesson.rule,
        "snippets": [{"label": s.label, "path": s.path, "symbol": s.symbol, "note": s.note}
                     for s in lesson.snippets],
        "demos": [{"label": d.label, "exhibit": d.exhibit, "variant": d.variant,
                   "tool": d.tool, "args": d.args, "note": d.note} for d in lesson.demos],
        "read_more": [{"label": label, "path": path} for label, path in lesson.read_more],
    }


async def main() -> None:
    log("capturing runs…")
    runs = await capture_runs()
    log("capturing tool surfaces and outputs…")
    surfaces, calls = await capture_tools()
    log("capturing primitives and wire frames…")
    primitives, wire = await capture_primitives()
    log("extracting source…")
    sources, snippets = capture_source()

    payload = {
        "exhibits": [
            {"id": ex.id, "title": ex.title, "pitfall": ex.pitfall, "question": ex.question,
             "bad_choice": ex.bad_choice, "good_choice": ex.good_choice,
             "bad_file": ex.bad_file, "good_file": ex.good_file, "watch": ex.watch,
             "focus": ex.focus, "default_runs": ex.default_runs, "paired": ex.paired,
             "questions": ex.questions, "mutates_db": ex.mutates_db}
            for ex in EXHIBITS.values()
        ],
        "lessons": {str(k): lesson_json(v) for k, v in LESSONS.items()},
        "primer": PRIMER,
        "primitives_doc": PRIMITIVES,
        "presets": PRESETS,
        "pairs": [{"id": ex.id, "title": ex.title, "bad_file": ex.bad_file,
                   "good_file": ex.good_file, "bad_choice": ex.bad_choice,
                   "good_choice": ex.good_choice}
                  for ex in EXHIBITS.values() if ex.paired],
        "db": {"counts": data.row_counts(), "tables": data.table_rows()},
        "tools": surfaces,
        "calls": calls,
        "runs": runs,
        "wire": wire,
        "primitives": primitives,
        "sources": sources,
        "snippets": snippets,
        "context_budget": settings.current().context_budget,
    }

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(
        "/* Generated by scripts/build_demo_data.py -- do not edit by hand.\n"
        "   Every number, tool output, trace and snippet in here was captured\n"
        "   from the real MCP servers over stdio. Re-run the script to refresh. */\n"
        "window.DEMO_DATA = "
        + json.dumps(payload, separators=(",", ":"), default=str)
        + ";\n"
    )
    log(f"wrote {OUT_FILE.relative_to(ROOT)} — {OUT_FILE.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    asyncio.run(main())
