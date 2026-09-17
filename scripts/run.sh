#!/bin/bash
set -euo pipefail
link_repo="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$link_repo/.venv/bin/laptop-link-mcp" ]]; then
    echo "Run scripts/setup.sh in $link_repo first." >&2
    exit 1
fi
exec "$link_repo/.venv/bin/laptop-link-mcp" \
    --bridge "$link_repo/dist/LaptopLinkBridge.app/Contents/MacOS/link-bridge" "$@"
