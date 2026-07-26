#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SECONDS="${CONTEST_TRADE_RUN_TIMEOUT_SECONDS:-1800}"

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/contesttrade" run \
  --market CN-Stock \
  --silent \
  --timeout-seconds "$TIMEOUT_SECONDS"
