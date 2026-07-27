#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SECONDS="${CONTEST_TRADE_RUN_TIMEOUT_SECONDS:-1800}"

cd "$PROJECT_DIR"

# systemd retries throughout the day so a reboot or transient network failure
# cannot permanently lose the 08:00 run. Keep retries idempotent: once today's
# report succeeds, every later wake-up exits without calling data or LLM APIs.
set +e
"$PROJECT_DIR/.venv/bin/python" - <<'PY'
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

now = datetime.now(ZoneInfo("Asia/Shanghai"))
today = now.date()

health_file = Path("contest_trade/agents_workspace/runtime/last_run.json")
try:
    health = json.loads(health_file.read_text(encoding="utf-8"))
except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
    health = {}

trigger_time = str(health.get("trigger_time") or "")
if health.get("status") in {"success", "degraded"} and trigger_time[:10] == today.isoformat():
    sys.exit(20)

# The mainland calendar endpoint is directly reachable from the deployment
# network. Do not make this single preflight depend on an optional proxy.
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(name, None)
calendar = ak.tool_trade_date_hist_sina()
trade_dates = set(pd.to_datetime(calendar["trade_date"]).dt.date)
sys.exit(0 if today in trade_dates else 10)
PY
calendar_status=$?
set -e

if [ "$calendar_status" -eq 10 ]; then
  echo "$(date -Iseconds) skip: not a CN trading day"
  exit 0
fi
if [ "$calendar_status" -eq 20 ]; then
  echo "$(date -Iseconds) skip: today's analysis already completed"
  exit 0
fi
if [ "$calendar_status" -ne 0 ]; then
  echo "$(date -Iseconds) error: unable to verify CN trading calendar" >&2
  exit "$calendar_status"
fi

exec "$PROJECT_DIR/.venv/bin/contesttrade" run \
  --market CN-Stock \
  --silent \
  --timeout-seconds "$TIMEOUT_SECONDS"
