#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SECONDS="${CONTEST_TRADE_RUN_TIMEOUT_SECONDS:-1800}"

cd "$PROJECT_DIR"

# systemd/cron can express weekdays, but not the mainland exchange holiday
# calendar.  Ask AKShare before starting an expensive model run and use a
# distinct exit code internally for a normal non-trading-day skip.
set +e
"$PROJECT_DIR/.venv/bin/python" - <<'PY'
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
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
if [ "$calendar_status" -ne 0 ]; then
  echo "$(date -Iseconds) error: unable to verify CN trading calendar" >&2
  exit "$calendar_status"
fi

exec "$PROJECT_DIR/.venv/bin/contesttrade" run \
  --market CN-Stock \
  --silent \
  --timeout-seconds "$TIMEOUT_SECONDS"
