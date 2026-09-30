#!/bin/bash
# start_bot.command — BẬT bot timesheet trên Mac (chạy nền).
# Nhấp đúp trong Finder. Bật nhiều lần không sao: bot tự chặn chạy trùng.
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE/src" || exit 1
PY="$BASE/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
mkdir -p "$BASE/data/logs"
nohup "$PY" bot.py >> "$BASE/data/logs/bot_console.log" 2>&1 &
echo "Da bat bot timesheet (chay nen). Co the dong cua so nay."
