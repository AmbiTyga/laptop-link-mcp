#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked
./scripts/build-bridge.sh
