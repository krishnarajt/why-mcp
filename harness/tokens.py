"""Token accounting.

The scoreboard is only persuasive if the numbers are honest, so:

  - PROMPT/COMPLETION tokens come from OpenAI's own `usage` field. Not
    estimated, not len//4 -- billed.
  - TOOL-SCHEMA tokens are counted locally with tiktoken, because no API call
    reports "how much of my prompt was tool definitions". This is the number
    exhibit 6 lives on: what you pay before the user says anything.
"""

from __future__ import annotations

import json

import tiktoken

_ENC = tiktoken.get_encoding("o200k_base")


def count(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


def schema_tokens(openai_tools: list[dict]) -> int:
    """What `tools/list` costs once serialised into the request.

    Every registered tool is charged on every request whether or not it is
    called. Forty tools is a standing tax, not a one-off.
    """
    if not openai_tools:
        return 0
    return count(json.dumps(openai_tools))


def messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += count(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            total += count(tc["function"]["name"] + tc["function"]["arguments"])
        total += 4  # per-message framing overhead
    return total
