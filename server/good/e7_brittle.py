"""EXHIBIT 7 (good) -- identical to the bad server, on purpose.

There is no good variant. `server/bad/e7_brittle.py` is imported verbatim.

That is the exhibit: a tool can pass every design rule in exhibits 1-6 --
task-shaped, bounded output, precise description, model-readable, read-only,
part of a small surface -- and still answer only 7 of 10 paraphrases of the
same question. Nothing in the code tells you which of your tools is the 7/10
one. Only running it N times does.

Do not fix this file. See PITFALLS.md.
"""

from __future__ import annotations

from server.bad.e7_brittle import register  # noqa: F401  (re-exported deliberately)
