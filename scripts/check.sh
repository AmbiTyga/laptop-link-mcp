#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pytest "$@"
