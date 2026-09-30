#!/bin/bash
# run_weekly.command — Chạy việc CHỐT TIMESHEET (weekly_run.py) bằng tay trên Mac.
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE/src" || exit 1
PY="$BASE/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
"$PY" weekly_run.py
echo "Xong. Xem tin nhan tren Telegram."
