#!/usr/bin/env bash
# Start the demo. Works with or without OPENAI_API_KEY (offline scripts).
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
exec uv run python -m app.main
