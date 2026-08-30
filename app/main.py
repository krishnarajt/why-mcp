"""The demo web app.

Runs are streamed over SSE so the audience watches the cost accrue rather than
seeing a finished number appear. On exhibit 1 you can count the round-trips as
they land; on exhibit 5 the row counter drops mid-sentence.

Runs are serialised behind a lock. Two exhibits sharing one SQLite file cannot
run concurrently without lying about exhibit 5, and a projector demo where two
things happen at once is a projector demo nobody follows.
"""

from __future__ import annotations

import ast
import asyncio
import json
import textwrap
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from harness import runner, settings, tokens
from harness.client import mcp_session, tool_result_text
from harness.exhibits import EXHIBITS
from harness.lessons import LESSONS, PRIMER, PRIMITIVES
from hr import data

ROOT = Path(__file__).parent.parent
INDEX = Path(__file__).parent / "index.html"

app = FastAPI(title="Why MCP -- Two Servers, One Question")
RUN_LOCK = asyncio.Lock()

# The static demo site (demo-site/, deployed to Vercel) can point its "Live mode"
# at a locally running copy of this app. That is a cross-origin call, so it needs
# CORS or the browser blocks it before the request is made. Wide open on purpose:
# this is a teaching demo that binds to localhost, reads a seeded database it
# reseeds on every run, and has no auth to protect. Do not copy this into
# anything that does.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only files the exhibits actually reference can be read by the source viewer.
SOURCE_ALLOWLIST = {ex.bad_file for ex in EXHIBITS.values()} | {
    ex.good_file for ex in EXHIBITS.values()
} | {
    "server/good/primitives.py", "harness/llm.py", "harness/client.py",
    "harness/exhibits.py", "harness/lessons.py", "harness/settings.py",
    "evals/selftest.py", "hr/data.py", "server/common.py",
}


@app.get("/")
def home():
    return FileResponse(INDEX)


@app.get("/api/exhibits")
def exhibits():
    return [
        {
            "id": ex.id,
            "title": ex.title,
            "pitfall": ex.pitfall,
            "question": ex.question,
            "bad_choice": ex.bad_choice,
            "good_choice": ex.good_choice,
            "bad_file": ex.bad_file,
            "good_file": ex.good_file,
            "watch": ex.watch,
            "focus": ex.focus,
            "default_runs": ex.default_runs,
            "paired": ex.paired,
            "questions": ex.questions,
            "mutates_db": ex.mutates_db,
        }
        for ex in EXHIBITS.values()
    ]


@app.get("/api/db")
def db_state():
    return {"counts": data.row_counts(), "total": sum(data.row_counts().values())}


@app.get("/api/db/preview")
def db_preview():
    return {"tables": data.table_rows()}


@app.post("/api/reset")
def reset():
    data.reset_db()
    return {"ok": True, "counts": data.row_counts()}


@app.get("/api/source")
def source(path: str):
    if path not in SOURCE_ALLOWLIST:
        raise HTTPException(404, "not an exhibit source file")
    target = ROOT / path
    if not target.is_file():
        raise HTTPException(404, "missing")
    return {"path": path, "code": target.read_text()}


def _lesson_json(lesson) -> dict:
    return {
        "headline": lesson.headline,
        "what_happens": lesson.what_happens,
        "why_tempting": lesson.why_tempting,
        "what_it_costs": lesson.what_it_costs,
        "rule": lesson.rule,
        "snippets": [
            {"label": sn.label, "path": sn.path, "symbol": sn.symbol, "note": sn.note}
            for sn in lesson.snippets
        ],
        "demos": [
            {"label": d.label, "exhibit": d.exhibit, "variant": d.variant,
             "tool": d.tool, "args": d.args, "note": d.note}
            for d in lesson.demos
        ],
        "read_more": [{"label": lbl, "path": path} for lbl, path in lesson.read_more],
    }


@app.get("/api/lessons")
def lessons():
    return {
        "primer": PRIMER,
        "primitives": PRIMITIVES,
        "lessons": {str(k): _lesson_json(v) for k, v in LESSONS.items()},
    }


def _find_symbol(tree: ast.AST, name: str) -> tuple[int, int] | None:
    """First def/class/assignment called `name`, anywhere -- including nested.

    Most tools in this repo are defined inside `register(mcp)`, so a top-level
    scan would miss all of them.
    """
    best: tuple[int, int] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name != name:
                continue
            # Start at the first decorator: @mcp.tool(annotations=...) is part of
            # the lesson, arguably the most important part.
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or start
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            start, end = node.lineno, node.end_lineno or node.lineno
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            (a.asname or a.name) == name for a in node.names
        ):
            # A re-export can BE the lesson: server/good/e7_brittle.py imports
            # the bad server's register verbatim, and that one line is the point.
            start, end = node.lineno, node.end_lineno or node.lineno
        else:
            continue
        if best is None or start < best[0]:
            best = (start, end)
    return best


@app.get("/api/snippet")
def snippet(path: str, symbol: str):
    """The real source of one symbol, extracted at request time.

    Nothing is pasted into the lesson text, so the page cannot drift out of sync
    with the code it teaches.
    """
    if path not in SOURCE_ALLOWLIST:
        raise HTTPException(404, "not an exhibit source file")
    target = ROOT / path
    if not target.is_file():
        raise HTTPException(404, "missing")
    src = target.read_text()
    found = _find_symbol(ast.parse(src), symbol)
    if found is None:
        raise HTTPException(404, f"no symbol {symbol!r} in {path}")
    start, end = found
    lines = src.splitlines()[start - 1 : end]
    return {
        "path": path,
        "symbol": symbol,
        "start_line": start,
        "end_line": end,
        "code": textwrap.dedent("\n".join(lines)),
    }


DEMO_INDEX = {
    (d.exhibit, d.variant, d.tool, json.dumps(d.args, sort_keys=True))
    for lesson in LESSONS.values()
    for d in lesson.demos
}


@app.get("/api/demo")
async def demo(exhibit: int, variant: str, tool: str, args: str = "{}"):
    """Call one real tool on one real server and return what the model would see.

    Allowlisted against the demos declared in lessons.py. That is not politeness:
    the bad exhibit-5 server has delete_employee and delete_paychecks on it, and
    this endpoint is reachable from a browser.
    """
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        raise HTTPException(400, "args must be JSON") from None
    key = (exhibit, variant, tool, json.dumps(parsed, sort_keys=True))
    if key not in DEMO_INDEX:
        raise HTTPException(403, "not a declared demo")

    runner._env_for_server()
    async with RUN_LOCK:
        async with mcp_session(variant, exhibit) as (session, _tap):
            result = await session.call_tool(tool, parsed)
            text = tool_result_text(result)
    return {
        "tool": tool, "args": parsed, "variant": variant, "exhibit": exhibit,
        "text": text, "chars": len(text), "tokens": tokens.count(text),
    }


def _config_payload() -> dict:
    import os

    cfg = settings.current()
    return {
        "model": cfg.model,
        "has_key": bool(os.environ.get("OPENAI_API_KEY")),
        "context_budget": cfg.context_budget,
        "max_tool_calls": cfg.max_tool_calls,
        "offline_mode": cfg.offline,
        "offline_now": runner.is_offline(),
    }


@app.get("/api/config")
def config():
    return _config_payload()


class SettingsPatch(BaseModel):
    model: str | None = None
    context_budget: int | None = None
    max_tool_calls: int | None = None
    offline: str | None = None


def _settings_payload() -> dict:
    """Current values, the cold-start defaults, and the bounds the UI enforces."""
    return {
        "current": settings.as_dict(),
        "defaults": settings.defaults_dict(),
        "config": _config_payload(),
        "limits": {
            "context_budget": [settings.BUDGET_MIN, settings.BUDGET_MAX],
            "max_tool_calls": [settings.CALLS_MIN, settings.CALLS_MAX],
            "offline": list(settings.OFFLINE_CHOICES),
        },
    }


@app.get("/api/settings")
def get_settings():
    return _settings_payload()


@app.post("/api/settings")
def post_settings(patch: SettingsPatch):
    """Apply a partial update. Refused mid-run, because a run that changed model
    halfway through would produce a scoreboard nobody could interpret."""
    if RUN_LOCK.locked():
        raise HTTPException(409, "a run is in progress -- wait for it to finish")
    try:
        settings.update(patch.model_dump(exclude_none=True))
    except settings.SettingsError as exc:
        raise HTTPException(400, str(exc)) from None
    return _settings_payload()


@app.post("/api/settings/reset")
def reset_settings():
    if RUN_LOCK.locked():
        raise HTTPException(409, "a run is in progress -- wait for it to finish")
    settings.reset()
    return _settings_payload()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


PRESETS = [
    {"pair": 3, "q": "Has this cost centre budget problem happened before?",
     "why": "the coin flip -- search or find?"},
    {"pair": 5, "q": "Tidy up the people whose payroll keeps failing so finance stops escalating.",
     "why": "watch the row counter"},
    {"pair": 2, "q": "Why did Marcus Bell's pay run break?",
     "why": "the 700k-char trace"},
    {"pair": 4, "q": "Whose payroll should I fix first?",
     "why": "raw JSON vs a table"},
    {"pair": 1, "q": "What failed last cycle, and did an org change cause it?",
     "why": "how many round-trips?"},
    {"pair": 6, "q": "What timezone are the payroll timestamps in?",
     "why": "47 tools vs 7"},
]

MAX_QUESTION = 500


@app.get("/api/playground")
def playground():
    """Server pairs you can point your own question at."""
    return {
        "presets": PRESETS,
        "max_question": MAX_QUESTION,
        "pairs": [
            {"id": ex.id, "title": ex.title, "bad_file": ex.bad_file,
             "good_file": ex.good_file, "bad_choice": ex.bad_choice,
             "good_choice": ex.good_choice}
            for ex in EXHIBITS.values()
            if ex.paired
        ],
    }


@app.get("/api/run")
async def run(exhibit: int, variant: str, run_index: int = 0, question: str | None = None):
    if exhibit not in EXHIBITS or variant not in ("bad", "good"):
        raise HTTPException(400, "bad exhibit or variant")
    if question is not None:
        question = question.strip()
        if not question:
            raise HTTPException(400, "empty question")
        if len(question) > MAX_QUESTION:
            raise HTTPException(400, f"question longer than {MAX_QUESTION} characters")

    async def stream():
        if RUN_LOCK.locked():
            yield _sse({"type": "error", "kind": "busy", "message": "another run is in progress"})
            return
        async with RUN_LOCK:
            try:
                async for event in runner.run_exhibit(
                    exhibit, variant, run_index=run_index, question=question
                ):
                    yield _sse(event)
            except Exception as exc:  # surface it in the UI, do not 500 silently
                yield _sse({"type": "error", "kind": "crash", "message": f"{type(exc).__name__}: {exc}"})
                yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------- the primitives tour ----------------


class PrimitiveCall(BaseModel):
    action: str
    arg: str = ""


@app.post("/api/primitive")
async def primitive(call: PrimitiveCall):
    """Fire one MCP primitive against the good server and return the wire frames."""
    runner._env_for_server()
    # Only sampling needs a model. Elicitation is answered by the client's own
    # callback, so it works with no key at all -- which is worth demonstrating.
    client = None
    if call.action == "sampling":
        if runner.is_offline():
            raise HTTPException(
                400,
                "Sampling needs a real model: the server is asking the CLIENT to run a "
                "completion. Add OPENAI_API_KEY to .env and retry.",
            )
        client = runner.openai_client()

    async with RUN_LOCK:
        async with mcp_session(
            "good", 0, openai_client=client, sampling_model=runner.model()
        ) as (session, tap):
            out: dict = {"action": call.action}
            if call.action == "tools":
                res = await session.list_tools()
                out["result"] = "\n".join(
                    f"{t.name}({', '.join((t.input_schema or {}).get('properties', {}))})"
                    f"\n    {(t.description or '').splitlines()[0] if t.description else ''}"
                    for t in res.tools
                )
            elif call.action == "resources":
                res = await session.list_resources()
                tpl = await session.list_resource_templates()
                out["result"] = "\n".join(
                    [f"{r.uri}  -- {r.name}" for r in res.resources]
                    + [f"{t.uri_template}  -- {t.name} (template)" for t in tpl.resource_templates]
                )
            elif call.action == "read_resource":
                res = await session.read_resource(call.arg or "hr://employees")
                out["result"] = res.contents[0].text[:2500]
            elif call.action == "prompts":
                res = await session.list_prompts()
                out["result"] = "\n".join(f"/{p.name}  -- {p.description}" for p in res.prompts)
            elif call.action == "get_prompt":
                res = await session.get_prompt("payroll_triage", {"days": "30"})
                out["result"] = "\n\n".join(
                    getattr(m.content, "text", "") for m in res.messages
                )
            elif call.action == "sampling":
                res = await session.call_tool("summarise_case", {"case_id": 1})
                out["result"] = tool_result_text(res)
            elif call.action == "elicitation":
                res = await session.call_tool("change_cost_center_budget", {})
                out["result"] = tool_result_text(res)
            else:
                raise HTTPException(400, f"unknown action {call.action!r}")
            out["frames"] = tap.frames
            return out


data.reset_db()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", port=1184, reload=True)
