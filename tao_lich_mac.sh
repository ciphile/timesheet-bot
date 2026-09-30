#!/bin/bash
# tao_lich_mac.sh — TẠO (hoặc tạo lại) lịch tự động launchd trên Mac:
#   com.timesheet.bot    : bật bot 16:00 hằng ngày
#   com.timesheet.weekly : chốt timesheet thứ 6 17:00
# Cách chạy:  bash ~/timesheet/tao_lich_mac.sh      (cài chỗ khác: thêm đường dẫn)
DEST="${1:-$HOME/timesheet}"; DEST="${DEST%/}"
[ -f "$DEST/src/bot.py" ] || { echo "[DUNG] Khong thay bot trong \"$DEST\"."; exit 1; }
PY="$DEST/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA" "$DEST/data/logs"
make_plist() {  # $1=label  $2=script  $3=<dict> lịch
  cat > "$LA/$1.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$DEST/src/$2</string></array>
  <key>WorkingDirectory</key><string>$DEST/src</string>
  <key>StartCalendarInterval</key>
  $3
  <key>StandardOutPath</key><string>$DEST/data/logs/launchd_$2.log</string>
  <key>StandardErrorPath</key><string>$DEST/data/logs/launchd_$2.log</string>
</dict>
</plist>
PLIST
  if command -v launchctl >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)" "$LA/$1.plist" 2>/dev/null
    launchctl bootstrap "gui/$(id -u)" "$LA/$1.plist" && echo "Da tao lich: $1"
  else
    echo "Da ghi file lich: $LA/$1.plist"
  fi
}
make_plist "com.timesheet.bot"    "bot.py"        "<dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>"
make_plist "com.timesheet.weekly" "weekly_run.py" "<dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>"
