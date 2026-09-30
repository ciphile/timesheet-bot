#!/bin/bash
# =====================================================================
#  cai_dat_mac.sh — Cài bot timesheet trên MAC (chạy 1 lần).
#  Cách chạy: mở Terminal, gõ   bash <kéo thả file này vào>   rồi Enter.
#  - Tạo thư mục, chép 28 file .py + file mẫu + cấu hình MẪU
#  - Tạo môi trường Python riêng (.venv) và cài thư viện
#  - (Tùy chọn) tạo lịch tự động launchd: bot 16:00 hằng ngày,
#    chốt timesheet thứ 6 17:00
#  AN TOÀN: thư mục đích ĐÃ CÓ bot (có config/secrets.env) → DỪNG LẠI.
# =====================================================================
REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/timesheet"
echo ""
echo "===== CAI DAT BOT TIMESHEET (Mac) ====="
echo "Thu muc cai dat mac dinh: $DEST"
read -r -p "Nhan ENTER de dung mac dinh, hoac go duong dan khac: " NHAP
# kéo thả thư mục vào Terminal có thể thêm dấu nháy / dấu \ trước khoảng trắng
NHAP="$(printf '%s' "$NHAP" | sed -e "s/^[\"']//" -e "s/[\"']\$//" -e 's/\\ / /g' -e 's/[[:space:]]*$//')"
[ -n "$NHAP" ] && DEST="${NHAP%/}"
if [ "$DEST" = "$REPO" ]; then
  echo "[DUNG] Thu muc cai dat trung voi thu muc tai ve. Chon thu muc KHAC (vd $HOME/timesheet)."; exit 1
fi
if [ -f "$DEST/config/secrets.env" ]; then
  echo "[DUNG] \"$DEST\" DA CO bot dang cai (co config/secrets.env)."
  echo "       De KHONG ghi de du lieu / cau hinh cua ban, bo cai dat DUNG LAI."; exit 1
fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "[DUNG] Chua co Python 3.10 tro len. Cai tu https://www.python.org/downloads/macos/ roi chay lai."; exit 1
fi
echo "[1/5] Tao thu muc trong \"$DEST\" ..."
mkdir -p "$DEST"/{src,config,template,data/logs,output,backup}
echo "[2/5] Chep file ..."
cp "$REPO"/src/*.py "$DEST/src/"
cp "$REPO/template/master_template.xlsx" "$DEST/template/"
for f in requirements.txt start_bot.command run_weekly.command restart_bot.command tao_lich_mac.sh README.md; do cp "$REPO/$f" "$DEST/"; done
[ -f "$DEST/config/settings.json" ] || cp "$REPO/config/settings.example.json" "$DEST/config/settings.json"
[ -f "$DEST/config/secrets.env" ]  || cp "$REPO/config/secrets.env.example"  "$DEST/config/secrets.env"
chmod +x "$DEST/start_bot.command" "$DEST/run_weekly.command" "$DEST/restart_bot.command" "$DEST/tao_lich_mac.sh"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null   # bỏ cờ "tải từ Internet" để nhấp đúp chạy được
N=$(ls "$DEST"/src/*.py 2>/dev/null | wc -l | tr -d ' ')
if [ "$N" = "28" ]; then echo "      Du 28/28 file .py"; else echo "[CANH BAO] Chi chep duoc $N/28 file .py"; fi
echo "[3/5] Tao moi truong Python rieng + cai thu vien (can Internet, 1-3 phut) ..."
python3 -m venv "$DEST/.venv" || { echo "[LOI] Khong tao duoc .venv"; exit 1; }
PY="$DEST/.venv/bin/python"
"$PY" -m pip install --upgrade pip >/dev/null 2>&1
"$PY" -m pip install -r "$DEST/requirements.txt" || echo "[CANH BAO] Cai thu vien bi loi - chup man hinh, xem README muc Su co."
echo "[4/5] Lich chay tu dong (launchd): bot 16:00 hang ngay + chot timesheet thu 6 17:00"
read -r -p "Tao lich tu dong ngay bay gio? [Y/N]: " YN
if [ "$YN" = "Y" ] || [ "$YN" = "y" ]; then
  bash "$DEST/tao_lich_mac.sh" "$DEST"
fi
echo "[5/5] Mo 2 file cau hinh de ban dien (lam theo README.md muc 3) ..."
if [ "$(uname)" = "Darwin" ]; then
  open -e "$DEST/config/secrets.env"; open -e "$DEST/config/settings.json"
fi
echo ""
echo "===== CAI DAT XONG ====="
echo "Dien xong 2 file cau hinh roi kiem tra:"
echo "   cd \"$DEST/src\""
echo "   ../.venv/bin/python config_loader.py"
echo "   ../.venv/bin/python selfcheck.py"
echo "Sau do bat bot: nhap dup \"$DEST/start_bot.command\""
