#!/bin/bash
# restart_bot.command — TẮT đúng tiến trình bot timesheet rồi BẬT LẠI (Mac).
# Dùng khi: đổi settings.json / secrets.env, cập nhật code, bot bị treo.
# Chỉ tắt chương trình đang chạy bot.py (không đụng chương trình khác).
BASE="$(cd "$(dirname "$0")" && pwd)"
echo "Dang tat bot timesheet (neu dang chay)..."
# Chỉ khớp tiến trình mà CHƯƠNG TRÌNH CHÍNH là python và THAM SỐ là bot.py
pkill -f '^[^ ]*[Pp]ython[0-9.]* ([^ ]*/)?bot\.py$' && echo "  Da tat bot." || echo "  (Bot dang khong chay.)"
sleep 3
echo "Dang bat lai bot..."
bash "$BASE/start_bot.command"
echo "Xong. Cho khoang 10 giay roi nhan /status cho bot tren Telegram."
