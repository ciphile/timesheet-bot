"""
housekeeping.py — Dọn dẹp định kỳ để dữ liệu không phình vô hạn.

Chạy tự động mỗi lần bot khởi động (1 lần/ngày là đủ, có cờ chống
chạy lại trong ngày). Nguyên tắc: CHỈ dọn thứ tái tạo được hoặc đã
hết giá trị sử dụng; KHÔNG bao giờ đụng file timesheet trong output\\.

Giữ bao lâu (sửa ở đây nếu muốn đổi):
  notes.jsonl        : 120 ngày  (ghi chú thô — nguồn sự thật, giữ lâu)
  parsed_days.json   : 120 ngày  (kết quả parse theo ngày)
  backup\\*.xlsx      :  90 ngày  (bản sao trước mỗi lần ghi)
  data\\preview\\*.xlsx:   7 ngày  (file xem trước, tái tạo được)
  audit.log          : cắt còn 5.000 dòng cuối khi vượt 20.000
  logs\\*.log         : log_setup đã tự xoay giữ 30 ngày (không đụng)
  sg_holidays_<year>.json : giữ 2 năm trước, KHÔNG đụng năm nay/sau
  KHÔNG BAO GIỜ ĐỤNG: mọi file .xlsx trong output\\ (file làm việc
  LẪN bản giao — cả hai đều là SẢN PHẨM timesheet, tuyệt đối không
  housekeep). Chỉ backup\\ (bản sao trước khi ghi) mới bị dọn.

Chạy tay:  python thư mục timesheet\\src\\housekeeping.py
"""

import json
import os
from datetime import date, datetime, timedelta

from config_loader import (BACKUP_DIR, DATA_DIR, NOTES_BAK_DIR,
                           PARSED_BAK_DIR, PARSED_SNAPSHOT_DIR, CORRUPT_DIR)
from log_setup import get_logger
from audit_log import audit

log = get_logger("housekeeping")

KEEP_NOTES_DAYS = 120
KEEP_PARSED_DAYS = 120
KEEP_BACKUP_DAYS = 90
KEEP_PREVIEW_DAYS = 7
KEEP_NOTES_BAK_DAYS = 30   # xóa notes.jsonl.bak_* cũ hơn 30 ngày
KEEP_PARSED_SNAPSHOT_DAYS = 60   # data\backup\parsed_days_daily\parsed_days_YYYYMMDD.json
KEEP_PARSED_BAK_DAYS = 90        # data\backup\parsed_days\parsed_days.json.bak_* (/resetnotes)
KEEP_CORRUPT_DAYS = 90           # data\backup\corrupt\parsed_days.json.corrupt_*

# HÀNG RÀO AN TOÀN: prune_old_files CHỈ được xóa trong các thư mục này.
# Gọi nhầm sang data\, output\... → từ chối, không xóa gì.
_PRUNE_ALLOWED = (BACKUP_DIR, DATA_DIR / "preview", NOTES_BAK_DIR,
                  PARSED_BAK_DIR, PARSED_SNAPSHOT_DIR, CORRUPT_DIR)
AUDIT_MAX_LINES = 20_000
AUDIT_KEEP_LINES = 5_000

LAST_RUN_FILE = DATA_DIR / "housekeeping_last_run.txt"


def _already_ran_today() -> bool:
    if not LAST_RUN_FILE.exists():
        return False
    try:
        return LAST_RUN_FILE.read_text(encoding="utf-8").strip() == \
            date.today().isoformat()
    except OSError as e:
        log.debug("Không đọc được housekeeping_last_run.txt (%s) — coi như chưa chạy.", e)
        return False


def _mark_ran_today() -> None:
    try:
        LAST_RUN_FILE.write_text(date.today().isoformat(), encoding="utf-8")
    except OSError as e:
        log.warning("Không ghi được mốc housekeeping: %s", e)


# ---------------------------------------------------------------------
# Từng việc dọn
# ---------------------------------------------------------------------

def prune_notes(cutoff: date) -> int:
    """Bỏ ghi chú cũ hơn cutoff. Trả số dòng đã bỏ."""
    path = DATA_DIR / "notes.jsonl"
    if not path.exists():
        return 0
    kept, dropped = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                note_date = date.fromisoformat(record["note_date"])
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.debug("Dòng notes.jsonl không parse được (%s) — giữ lại nguyên văn.", e)
                kept.append(line)
                continue
            if note_date < cutoff:
                dropped += 1
            else:
                kept.append(line)
    if dropped:
        # Ghi ATOMIC (tmp + os.replace): notes.jsonl là NGUỒN SỰ THẬT
        # của mọi ghi chú — máy tắt đột ngột giữa lúc ghi đè tuyệt
        # đối không được để mất một phần dữ liệu thật.
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
        os.replace(tmp, path)
    return dropped


def snapshot_parsed_days() -> str:
    """Chụp 1 bản parsed_days.json MỖI NGÀY vào backup\\parsed_days\\
    (thêm 24-Sep). Chạy TRƯỚC prune_parsed_days. Bỏ qua nếu file đang
    hỏng (không chụp rác) hoặc hôm nay đã chụp. Trả tên file hoặc ""."""
    import daily_store, shutil
    src = daily_store.PARSED_FILE
    if not src.exists():
        return ""
    try:
        json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Không chụp backup parsed_days: file đang hỏng (%s).", e)
        return ""
    dest_dir = PARSED_SNAPSHOT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"parsed_days_{date.today():%Y%m%d}.json"
    if dest.exists():
        return ""
    shutil.copy(src, dest)   # copy (KHÔNG copy2) → ngày sửa = hôm nay, để dọn đúng hạn
    return dest.name


def prune_parsed_days(cutoff: date) -> int:
    import daily_store
    return daily_store.prune_before(cutoff)


def refresh_ai_model_cache(config=None) -> dict:
    """Dò lại model AI nếu cache hết hạn. Gọi mỗi lần bot khởi động
    để đảm bảo cache LUÔN ĐƯỢC CẬP NHẬT đúng hạn, dù người dùng không
    nhắn tin gì trong nhiều tuần. Lỗi chỉ log, không block bot."""
    try:
        from ai_client import refresh_model_cache_if_needed
        from config_loader import load_config
        cfg = config or load_config()
        return refresh_model_cache_if_needed(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("Refresh AI model cache lỗi: %s", e)
        return {"refreshed": False, "model": "", "reason": str(e)}


def prune_holiday_caches() -> int:
    """Dọn cache lịch nghỉ lễ MOM của các năm đã qua lâu (giữ 2 năm
    trước để còn tra cứu/đối chiếu). Không đụng năm hiện tại/năm sau.
    Đồng thời dọn holiday_fetch_status.json cho các năm cũ."""
    import sg_holidays, json, os
    from datetime import date
    removed = sg_holidays.prune_old_caches()

    # Dọn status file: chỉ giữ năm hiện tại và năm sau
    status_file = sg_holidays._FETCH_STATUS_FILE
    if status_file.exists():
        try:
            status = json.loads(status_file.read_text(encoding='utf-8'))
            keep_years = {str(date.today().year), str(date.today().year + 1)}
            cleaned = {k: v for k, v in status.items() if k in keep_years}
            if len(cleaned) < len(status):
                tmp = status_file.with_suffix('.json.tmp')
                tmp.write_text(json.dumps(cleaned, ensure_ascii=False,
                               indent=2), encoding='utf-8')
                os.replace(tmp, status_file)
                removed += len(status) - len(cleaned)
        except Exception as e:
            log.warning("Không dọn được holiday_fetch_status.json: %s", e)
    return removed


def migrate_old_backups() -> int:
    """Dời backup ở CHỖ CŨ sang data\\backup\\ (24-Sep). Chạy mỗi lượt,
    rẻ; hết file cũ thì không làm gì. shutil.move GIỮ ngày sửa file →
    file cũ vẫn bị dọn đúng tuổi thật của nó."""
    import shutil
    moves = [
        (DATA_DIR, "notes.jsonl.bak_*", NOTES_BAK_DIR),
        (DATA_DIR, "parsed_days.json.bak_*", PARSED_BAK_DIR),
        (DATA_DIR, "parsed_days.json.corrupt_*", CORRUPT_DIR),
        (BACKUP_DIR / "parsed_days", "parsed_days_*.json", PARSED_SNAPSHOT_DIR),
    ]
    moved = 0
    for src_dir, pattern, dest in moves:
        if not src_dir.exists():
            continue
        for p in src_dir.glob(pattern):
            if not p.is_file():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / p.name
            if target.exists():          # trùng tên (hiếm) → không ghi đè
                target = dest / f"{p.stem}_dup{p.suffix}"
            try:
                shutil.move(str(p), str(target))
                moved += 1
            except OSError as e:
                log.warning("Không dời được %s: %s", p.name, e)
    old = BACKUP_DIR / "parsed_days"
    try:
        if old.exists() and not any(old.iterdir()):
            old.rmdir()
    except OSError:
        pass
    return moved


def prune_old_files(folder, days: int, pattern: str = "*.xlsx") -> int:
    """Xóa file cũ hơn N ngày trong 1 thư mục (CHỈ thư mục trong
    _PRUNE_ALLOWED, CHỈ file khớp pattern, KHÔNG đi vào thư mục con)."""
    try:
        res = folder.resolve()
        ok = any(res == a.resolve() for a in _PRUNE_ALLOWED)
    except OSError:
        ok = False
    if not ok:
        log.error("prune_old_files TỪ CHỐI thư mục ngoài danh sách an toàn: %s",
                  folder)
        return 0
    if not folder.exists():
        return 0
    limit = datetime.now() - timedelta(days=days)
    removed = 0
    for path in folder.glob(pattern):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < limit:
                path.unlink()
                removed += 1
        except OSError as e:
            log.warning("Không xóa được %s: %s", path.name, e)
    return removed


def trim_audit_log() -> int:
    """Cắt bớt audit.log khi quá dài, giữ phần mới nhất."""
    path = DATA_DIR / "audit.log"
    if not path.exists():
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        log.warning("Không đọc được audit.log để cắt bớt (%s).", e)
        return 0
    if len(lines) <= AUDIT_MAX_LINES:
        return 0
    dropped = len(lines) - AUDIT_KEEP_LINES
    tmp = path.with_suffix(".log.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"# (đã cắt {dropped} dòng cũ lúc "
                f"{datetime.now():%Y-%m-%d %H:%M})\n")
        f.writelines(lines[-AUDIT_KEEP_LINES:])
    os.replace(tmp, path)
    return dropped


# ---------------------------------------------------------------------
# Chạy tất cả
# ---------------------------------------------------------------------

def run(force: bool = False) -> dict:
    """Dọn dẹp 1 lượt. Mặc định mỗi ngày chỉ chạy 1 lần."""
    if not force and _already_ran_today():
        log.debug("Housekeeping hôm nay chạy rồi — bỏ qua.")
        return {}

    today = date.today()
    result = {
        "migrated_backups": migrate_old_backups(),   # dời backup chỗ cũ → data\\backup
        "parsed_snapshot": snapshot_parsed_days(),   # TRƯỚC khi tỉa ngày cũ
        "notes": prune_notes(today - timedelta(days=KEEP_NOTES_DAYS)),
        "parsed_days": prune_parsed_days(
            today - timedelta(days=KEEP_PARSED_DAYS)),
        "backup": prune_old_files(BACKUP_DIR, KEEP_BACKUP_DAYS),
        "preview": prune_old_files(DATA_DIR / "preview", KEEP_PREVIEW_DAYS),
        "notes_bak": prune_old_files(NOTES_BAK_DIR, KEEP_NOTES_BAK_DAYS,
                                     pattern="notes.jsonl.bak_*"),
        "parsed_snapshot_old": prune_old_files(
            PARSED_SNAPSHOT_DIR, KEEP_PARSED_SNAPSHOT_DAYS,
            pattern="parsed_days_*.json"),
        "parsed_bak": prune_old_files(PARSED_BAK_DIR, KEEP_PARSED_BAK_DAYS,
                                      pattern="parsed_days.json.bak_*"),
        "parsed_corrupt": prune_old_files(CORRUPT_DIR, KEEP_CORRUPT_DAYS,
                                          pattern="parsed_days.json.corrupt_*"),
        "audit_lines": trim_audit_log(),
        "holiday_caches": prune_holiday_caches(),
        "ai_model_cache": refresh_ai_model_cache(),
    }
    _mark_ran_today()

    if any(result.values()):
        log.info("Housekeeping: %s", result)
        audit("HOUSEKEEPING", str(result))
    else:
        log.debug("Housekeeping: không có gì để dọn.")
    return result


if __name__ == "__main__":
    print("Dọn dẹp dữ liệu cũ…")
    print("Kết quả:", run(force=True) or "không có gì để dọn")
