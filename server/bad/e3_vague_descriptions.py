"""EXHIBIT 3 (bad) -- the description IS the prompt, and this one says nothing.

DESIGN CHOICE: two tools called `search` and `find`, documented as "Search."
and "Find things."

Both names are plausible. Both descriptions are true. Neither tells the model
the one thing that decides the call:

  search() covers PAYROLL TRACES -- last 12 months only, live data
  find()   covers CLOSED HR CASE FILES -- years of history

Asked "has this happened before?", the model picks by vibes. Worse, picking
wrong does not error: `search` cheerfully returns *last cycle's* failure, so
the model confidently reports the current problem as the precedent. A silent
wrong answer is the expensive kind.

Run this exhibit five times and watch the choice flip. That non-determinism is
the lesson: your tool descriptions are prompt engineering, and untested prompts
are coin flips.
"""

from __future__ import annotations

from hr import data
from server.common import dumps


def register(mcp) -> None:
    @mcp.tool()
    def search(q: str) -> str:
        """Search."""
        return dumps(data.search_traces(q))

    @mcp.tool()
    def find(q: str) -> str:
        """Find things."""
        rows = data.search_hr_cases(q)
        return dumps([dict(r) for r in rows])

    @mcp.tool()
    def lookup(q: str) -> str:
        """Look up data."""
        rows = data.q("SELECT * FROM employees WHERE name LIKE ?", (f"%{q}%",))
        return dumps([dict(r) for r in rows])
