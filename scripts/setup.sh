#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
link_setup_mode="${1:-all}"
if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [--build-only | --key-only]" >&2
    exit 2
fi
case "$link_setup_mode" in
    all|--build-only|--key-only) ;;
    *) echo "Usage: $0 [--build-only | --key-only]" >&2; exit 2 ;;
esac
if [[ "$link_setup_mode" != --key-only ]]; then
    uv sync --locked
    ./scripts/build-bridge.sh
fi
if [[ "$link_setup_mode" != --build-only ]]; then
    if [[ ! -x .venv/bin/python || ! -x dist/LaptopLinkBridge.app/Contents/MacOS/link-bridge ]]; then
        echo 'Run scripts/setup.sh first to install dependencies and build the bridge.' >&2
        exit 1
    fi
    .venv/bin/python -m laptop_link_mcp.enrollment
    echo 'Setup complete. Register scripts/run.sh with your MCP client; the downloaded key is selected automatically.'
else
    echo 'Build complete. Supply --key PATH when launching, or run scripts/setup.sh --key-only.'
fi
