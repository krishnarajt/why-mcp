"""stdio entrypoint -- the same code path a real MCP client uses.

    uv run python -m server bad  --exhibit 1
    uv run python -m server good --exhibit 6
    uv run python -m server good --exhibit 0     # primitives tour

This is what `.mcp.json` launches, and what the demo harness spawns. Using one
entrypoint for both means the numbers on the scoreboard come from exactly the
transport your editor would use, not a shortcut.
"""

from __future__ import annotations

import argparse

from server import bad, good


def main() -> None:
    ap = argparse.ArgumentParser(prog="server")
    ap.add_argument("variant", choices=["bad", "good"])
    ap.add_argument("--exhibit", type=int, default=1)
    ap.add_argument(
        "--transport", default="stdio", choices=["stdio", "streamable-http", "sse"]
    )
    args = ap.parse_args()

    builder = bad.build if args.variant == "bad" else good.build
    builder(args.exhibit).run(transport=args.transport)


if __name__ == "__main__":
    main()
