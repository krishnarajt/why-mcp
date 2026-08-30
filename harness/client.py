"""An MCP client with a wire tap.

Two jobs:

1. Speak real MCP. The server is spawned as a subprocess over stdio -- the same
   transport and the same entrypoint your editor would use. Nothing here
   shortcuts the protocol, because a demo that shortcuts the protocol cannot
   teach it.

2. Record every frame. `WireTap` wraps the read and write streams and copies
   each JSON-RPC message into a list, which is what the Primitives tab renders.
   Seeing `initialize` -> `tools/list` -> `tools/call` scroll past is how the
   protocol stops being abstract.

It also implements the two client-side callbacks most clients skip:
`sampling_callback` (the server asking OUR model for a completion) and
`elicitation_callback` (the server asking the USER a question). Implementing
them is what makes the primitives tour demonstrable rather than theoretical.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class WireTap:
    """Copies every JSON-RPC frame that crosses the transport."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def record(self, direction: str, msg: Any) -> None:
        payload = getattr(msg, "message", None)
        if payload is None:  # an exception came down the read stream
            self.frames.append({"dir": direction, "error": repr(msg)})
            return
        try:
            body = payload.model_dump(exclude_none=True, by_alias=True)
        except Exception:
            body = {"repr": repr(payload)}
        self.frames.append(
            {
                "dir": direction,
                "method": body.get("method") or ("result" if "result" in body else "error"),
                "id": body.get("id"),
                "body": body,
            }
        )


class _TappedRead:
    def __init__(self, inner, tap: WireTap) -> None:
        self._inner, self._tap = inner, tap

    async def receive(self):
        msg = await self._inner.receive()
        self._tap.record("server->client", msg)
        return msg

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    async def __aiter__(self):
        # The SDK's dispatcher iterates the stream rather than calling
        # receive(), so the tap has to live here too or every server->client
        # frame is invisible.
        async for msg in self._inner:
            self._tap.record("server->client", msg)
            yield msg

    def __getattr__(self, name):  # aclose, and anything else the SDK reaches for
        return getattr(self._inner, name)


class _TappedWrite:
    def __init__(self, inner, tap: WireTap) -> None:
        self._inner, self._tap = inner, tap

    async def send(self, msg):
        self._tap.record("client->server", msg)
        return await self._inner.send(msg)

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    def __aiter__(self):
        return self._inner.__aiter__()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _sampling_callback(openai_client, model: str):
    """The server asks OUR model. Inverted control flow, on the wire."""

    async def cb(context, params: types.CreateMessageRequestParams):
        msgs = []
        if params.system_prompt:
            msgs.append({"role": "system", "content": params.system_prompt})
        for m in params.messages:
            text = getattr(m.content, "text", "")
            msgs.append({"role": m.role, "content": text})
        resp = await openai_client.chat.completions.create(
            model=model, messages=msgs, max_tokens=params.max_tokens or 256
        )
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=resp.choices[0].message.content or ""),
            model=model,
            stopReason="endTurn",
        )

    return cb


def _elicitation_callback(answers: dict[str, Any] | None):
    """A real client would draw a form. The demo auto-accepts with canned values
    so the frame is visible without a human in the loop."""

    async def cb(context, params):
        return types.ElicitResult(
            action="accept",
            content=answers or {"limit_usd": 500000, "reason": "demo auto-accept"},
        )

    return cb


@asynccontextmanager
async def mcp_session(
    variant: str,
    exhibit: int,
    *,
    openai_client=None,
    sampling_model: str = "gpt-4o-mini",
    elicit_answers: dict[str, Any] | None = None,
):
    """Spawn `python -m server <variant> --exhibit N` and hand back a live session."""
    tap = WireTap()
    params = StdioServerParameters(
        command=os.environ.get("PYTHON_BIN", "python"),
        args=["-m", "server", variant, "--exhibit", str(exhibit)],
        cwd=str(os.environ.get("WHY_MCP_ROOT", ".")),
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            _TappedRead(read, tap),
            _TappedWrite(write, tap),
            sampling_callback=_sampling_callback(openai_client, sampling_model)
            if openai_client
            else None,
            elicitation_callback=_elicitation_callback(elicit_answers),
        ) as session:
            await session.initialize()
            yield session, tap


def tool_result_text(result: types.CallToolResult) -> str:
    """Exactly what we forward to the model -- and therefore exactly what we bill.

    Note we take `content` only, never `structuredContent`. A str-returning tool
    ships its payload twice in MCP 2.x; forwarding both would double-charge
    every measurement on the scoreboard. Real clients differ here, which is
    itself worth knowing.
    """
    parts = [getattr(c, "text", "") for c in (result.content or [])]
    return "\n".join(p for p in parts if p)
