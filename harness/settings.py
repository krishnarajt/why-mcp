"""Runtime knobs, changeable from the Settings tab without a restart.

Defaults come from the environment (`.env`), so the file on disk is still the
source of truth for a cold start. Everything here is a *session* override: it
lives in this process, applies to every subsequent run, and is thrown away when
you restart.

Why these four and not more: each one measurably moves something on the
scoreboard, and each one teaches a different half of the same point.

  MODEL           changes which tools get called. It cannot change what a tool
                  RETURNS, so it moves exhibits 1/3/5/6/7 and leaves exhibits
                  2, 4 and 6's schema number exactly where they are.
  CONTEXT_BUDGET  is exhibit 2's OVERFLOW line, drawn by hand. Raise it past
                  236k and the bad server "works" -- at a price nobody would
                  pay. Drop it to 5k and exhibit 4 starts overflowing too.
  MAX_TOOL_CALLS  is the cap on flailing. Exhibits 1, 3 and 6 are the ones that
                  flail; raising it buys the bad server more rope.
  OFFLINE         swaps the model for a fixed script. Everything mechanical
                  stays identical, which is the point of having it.

Deliberately NOT exposed: the system prompt and the servers' `instructions`.
Both are real levers, and both are what this demo holds constant so that tool
design is the only variable. Making them adjustable would let you tune your way
out of a pitfall and conclude the pitfall was not real.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

# This module owns the defaults, so it has to be the one that loads .env --
# `runner` calls load_dotenv() too, but only *after* its imports, by which point
# this module has already snapshotted the environment.
load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_MODEL = "gpt-4o-mini"

# Bounds exist so a typo produces a rejection rather than a mystifying run.
BUDGET_MIN, BUDGET_MAX = 1_000, 1_000_000
CALLS_MIN, CALLS_MAX = 1, 50
OFFLINE_CHOICES = ("auto", "on", "off")


@dataclass(frozen=True)
class Settings:
    model: str
    context_budget: int
    max_tool_calls: int
    # "auto" = offline only when there is no API key. "on"/"off" force it.
    offline: str


def _from_env() -> Settings:
    return Settings(
        model=os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
        context_budget=int(os.environ.get("WHY_MCP_CONTEXT_BUDGET") or 24_000),
        max_tool_calls=int(os.environ.get("WHY_MCP_MAX_TOOL_CALLS") or 20),
        offline="on" if os.environ.get("WHY_MCP_OFFLINE") == "1" else "auto",
    )


DEFAULTS = _from_env()
_current = DEFAULTS


def current() -> Settings:
    return _current


def as_dict() -> dict:
    return asdict(_current)


def defaults_dict() -> dict:
    return asdict(DEFAULTS)


class SettingsError(ValueError):
    """A rejected update. The message is shown to the user verbatim."""


def _int_in(name: str, value, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} must be a whole number.") from None
    if not lo <= n <= hi:
        raise SettingsError(f"{name} must be between {lo:,} and {hi:,} (got {n:,}).")
    return n


def update(patch: dict) -> Settings:
    """Validate and apply a partial update. Raises SettingsError on bad input."""
    global _current
    new = _current

    if "model" in patch and patch["model"] is not None:
        model = str(patch["model"]).strip()
        if not model:
            raise SettingsError("Model cannot be empty.")
        if len(model) > 80 or any(c.isspace() for c in model):
            raise SettingsError("That does not look like a model id.")
        new = replace(new, model=model)

    if "context_budget" in patch and patch["context_budget"] is not None:
        new = replace(
            new,
            context_budget=_int_in(
                "Context budget", patch["context_budget"], BUDGET_MIN, BUDGET_MAX
            ),
        )

    if "max_tool_calls" in patch and patch["max_tool_calls"] is not None:
        new = replace(
            new,
            max_tool_calls=_int_in(
                "Max tool calls", patch["max_tool_calls"], CALLS_MIN, CALLS_MAX
            ),
        )

    if "offline" in patch and patch["offline"] is not None:
        mode = str(patch["offline"]).strip().lower()
        if mode not in OFFLINE_CHOICES:
            raise SettingsError(f"Offline mode must be one of {', '.join(OFFLINE_CHOICES)}.")
        new = replace(new, offline=mode)

    _current = new
    return _current


def reset() -> Settings:
    global _current
    _current = DEFAULTS
    return _current
