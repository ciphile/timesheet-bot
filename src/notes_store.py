"""
notes_store.py — Kho ghi chú công việc hằng ngày.

Lưu ở data\\notes.jsonl theo dạng JSONL: mỗi dòng là 1 bản ghi JSON.
Vẫn là file chữ, mở bằng Notepad đọc được bình thường, ví dụ:

    {"saved_at": "2026-09-14T21:10:05", "note_date": "2026-09-14",
     "text": "fix bug login PACSNP-7660"}

- sent_at  : thời điểm NGƯỜI DÙNG GỬI tin (Telegram gắn vào tin nhắn)
- saved_at : thời điểm bot ghi xuống file
- note_date: ngày công việc = ngày GỬI, không phải ngày bot xử lý.
  Quan trọng: bot chỉ chạy 16:00-22:50, tin nhắn gửi ngoài khung giờ
  đó nằm xếp hàng tới lúc bot bật mới nhận. Nếu lấy ngày xử lý thì
  tin nhắn 23h30 thứ 2 sẽ bị gán nhầm sang thứ 3 (bug đã vá 15-Sep).
  Thứ 6 AI vẫn dùng cả timestamp lẫn nội dung ("hôm qua mình...") để
  xếp đúng ngày.
- Chỉ APPEND (ghi thêm), không bao giờ sửa/xóa dòng cũ → không mất
  dữ liệu, và audit được trọn vẹn.
"""

import json
import os
from datetime import date, datetime

from config_loader import DATA_DIR
from log_setup import get_logger

# Trước 24-Sep file này dùng log.xxx ở 4 nhánh xử lý lỗi nhưng CHƯA
# từng khai báo `log` → chạy tới nhánh đó là NameError sập bot.
log = get_logger("notes_store")

NOTES_FILE = DATA_DIR / "notes.jsonl"


def add_note(text: str, sent_at: datetime = None) -> dict:
    """Ghi 1 ghi chú mới, trả về bản ghi vừa lưu.

    sent_at: thời điểm người dùng GỬI tin (giờ địa phương). Bot truyền vào
    từ update.effective_message.date. Không truyền -> lấy giờ hiện tại
    (dùng cho test hoặc lệnh nội bộ).

    Chuẩn hóa ngày: các cụm ngày tường minh ("15/09", "thứ Ba tuần này",
    "hôm qua"...) trong text được chuyển thành dạng "15/09/2026 (thứ Ba)"
    trước khi lưu. Nhờ vậy AI không cần nhận dạng nhiều format khác nhau
    cho cùng một ngày — mọi ghi chú đều nhất quán khi đến tay Gemini."""
    sent_at = sent_at or datetime.now()
    sent_date = sent_at.date()

    # Chuẩn hóa cụm ngày tường minh — giữ nguyên text mơ hồ
    try:
        from date_normalizer import normalize_dates_in_text, normalize_hours_in_text
        normalized_text = normalize_hours_in_text(
            normalize_dates_in_text(text.strip(), sent_date))
    except Exception as e:  # noqa: BLE001 — chuẩn hóa hỏng không được mất ghi chú
        log.warning("Chuẩn hóa ngày/giờ trong ghi chú thất bại (%s) — dùng text gốc.", e)
        normalized_text = text.strip()

    record = {
        "sent_at": sent_at.isoformat(timespec="seconds"),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "note_date": sent_date.isoformat(),
        "text": normalized_text,
        "text_original": text.strip() if normalized_text != text.strip() else None,
    }
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_all_notes() -> list:
    """Đọc toàn bộ ghi chú, trả về list các dict (cũ trước, mới sau).
    Dòng nào hỏng (không phải JSON) thì bỏ qua thay vì sập."""
    if not NOTES_FILE.exists():
        return []
    notes = []
    with open(NOTES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.debug("Bỏ qua dòng notes.jsonl hỏng (%s).", e)
                continue
    return notes


def get_latest_note() -> dict | None:
    """Trả ghi chú gần nhất (dòng cuối của notes.jsonl).
    Dùng để biết tin nhắn mới nhất của người dùng đề cập ngày nào."""
    if not NOTES_FILE.exists():
        return None
    last = None
    try:
        with open(NOTES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return last


def mark_delete_executed(day) -> None:
    """Đánh dấu lệnh xóa ngày `day` đã được thực thi.
    Ghi tombstone '[DELETED:YYYY-MM-DD]' (dạng ISO, KHÔNG normalize)
    để AI biết lần sau không tái xóa. Chỉ là metadata nội bộ.

    QUAN TRỌNG: ghi THẲNG, không qua add_note() — vì add_note chạy
    normalize_dates_in_text sẽ biến [DELETED:2026-09-18] thành
    [DELETED:18/09/2026 (thứ Sáu)] gây bẩn tombstone."""
    marker_iso = f"[DELETED:{day.isoformat()}]"
    # Kiểm tra đã có marker chưa (tránh ghi trùng)
    if NOTES_FILE.exists():
        try:
            content = NOTES_FILE.read_text(encoding="utf-8")
            if marker_iso in content:
                return
        except OSError:
            pass
    # Ghi thẳng record, KHÔNG normalize
    now = datetime.now()
    record = {
        "sent_at": now.isoformat(timespec="seconds"),
        "saved_at": now.isoformat(timespec="seconds"),
        "note_date": day.isoformat(),
        "text": marker_iso,           # giữ nguyên ISO, không normalize
        "text_original": marker_iso,
    }
    try:
        with open(NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("Ghi tombstone thất bại (%s).", e)
    import logging
    logging.getLogger("notes_store").debug("mark_delete_executed: %s", marker_iso)


def clear_notes_only() -> dict:
    """Xóa sạch notes.jsonl (ghi chú thô) NHƯNG giữ nguyên parsed_days.

    An toàn: backup notes.jsonl thành notes.jsonl.bak_<timestamp> trước
    khi xóa, phòng khi cần tra cứu. KHÔNG đụng parsed_days.json,
    state.json, hay bất kỳ file nào khác.

    Dùng để dọn sạch dấu vết xóa/ghi chú lặp gây nhiễu AI, trong khi
    vẫn giữ toàn bộ dữ liệu đã parse (để tạo Excel, xem summary...).

    Trả dict: {"had_notes": bool, "backup": str|None, "line_count": int}
    """
    if not NOTES_FILE.exists():
        return {"had_notes": False, "backup": None, "line_count": 0}

    # Đếm số dòng trước khi xóa
    try:
        content = NOTES_FILE.read_text(encoding="utf-8")
        line_count = len([l for l in content.splitlines() if l.strip()])
    except OSError:
        line_count = 0

    # File tồn tại nhưng rỗng → coi như không có gì để xóa
    if line_count == 0:
        return {"had_notes": False, "backup": None, "line_count": 0}

    import logging
    _log = logging.getLogger("notes_store")

    # Backup trước khi xóa
    backup_name = None
    try:
        import shutil
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        from config_loader import NOTES_BAK_DIR
        NOTES_BAK_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = NOTES_BAK_DIR / f"notes.jsonl.bak_{stamp}"
        shutil.copy2(NOTES_FILE, backup_path)
        backup_name = backup_path.name
    except OSError as e:
        _log.warning("Backup notes.jsonl thất bại (%s) — vẫn tiếp tục xóa.", e)

    # Xóa nội dung (ghi file rỗng, giữ file để không lỗi đọc sau này)
    try:
        NOTES_FILE.write_text("", encoding="utf-8")
        _log.info("Đã xóa notes.jsonl (%d dòng), backup: %s. "
                  "parsed_days.json GIỮ NGUYÊN.",
                  line_count, backup_name or "(thất bại)")
    except OSError as e:
        _log.error("Xóa notes.jsonl thất bại: %s", e)
        return {"had_notes": True, "backup": backup_name,
                "line_count": line_count, "error": str(e)}

    return {"had_notes": True, "backup": backup_name,
            "line_count": line_count}


def clear_delete_tombstone(day) -> None:
    """Xóa DẤU VẾT XÓA của `day` khỏi notes.jsonl khi có ghi chú mới:
    (1) tombstone [DELETED:day] (cả format ISO lẫn normalized cũ)
    (2) lệnh "xóa ngày day" cũ — vì nếu để lại, AI đọc thấy sẽ tưởng
        vẫn muốn xóa dù người dùng đã nhập lại ngày đó.
    Ghi chú mới THẮNG mọi dấu vết xóa cũ của ngày đó.
    """
    marker_iso = f"[DELETED:{day.isoformat()}]"
    marker_dmy = f"[DELETED:{day.strftime('%d/%m/%Y')}"  # normalized cũ
    # Chuỗi ngày để nhận lệnh xóa cũ: "15/09/2026"
    day_dmy = day.strftime("%d/%m/%Y")
    DELETE_WORDS = ("xóa", "xoá", "bỏ ngày", "bỏ task", "delete",
                    "xóa dữ liệu", "xoá dữ liệu")

    if not NOTES_FILE.exists():
        return
    try:
        lines = NOTES_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    kept = []
    removed_tomb = 0
    removed_cmd = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        txt = obj.get("text", "")
        txt_orig = obj.get("text_original") or ""

        # (1) tombstone
        is_tombstone = (marker_iso in txt or marker_iso in txt_orig
                        or marker_dmy in txt or marker_dmy in txt_orig)
        if is_tombstone:
            removed_tomb += 1
            continue

        # (2) lệnh xóa CŨ của ngày này: text có từ khóa xóa VÀ có ngày day
        #     VÀ không phải ghi chú task (chỉ là lệnh xóa thuần)
        low = txt.lower()
        has_del_word = any(w in low for w in DELETE_WORDS)
        has_this_day = day_dmy in txt or day.isoformat() in txt
        # Lệnh xóa thuần: ngắn, chủ yếu là "xóa ngày X" (không có task/ticket)
        is_pure_delete_cmd = (
            has_del_word and has_this_day
            and len(txt) < 60          # lệnh xóa thường ngắn
            and "PACS" not in txt.upper()  # không chứa ticket = không phải ghi chú task
            and "DFU" not in txt.upper()
            and "SDF" not in txt.upper())
        if is_pure_delete_cmd:
            removed_cmd += 1
            continue

        kept.append(line)

    if removed_tomb or removed_cmd:
        try:
            tmp = NOTES_FILE.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")
            os.replace(tmp, NOTES_FILE)
            import logging
            logging.getLogger("notes_store").info(
                "Dọn dấu vết xóa ngày %s: %d tombstone + %d lệnh xóa cũ "
                "(có ghi chú mới về ngày này).",
                day.isoformat(), removed_tomb, removed_cmd)
        except OSError:
            pass


def cleanup_stale_delete_traces() -> int:
    """Quét toàn bộ notes, dọn dấu vết xóa LỖI THỜI:
    Với mỗi ngày X có tombstone [DELETED:X] hoặc lệnh "xóa ngày X",
    nếu SAU dấu vết đó có ghi chú THẬT (task) về ngày X → dấu vết xóa
    đã lỗi thời (người dùng nhập lại) → dọn đi.

    Gọi định kỳ (housekeeping) hoặc trước mỗi lần parse để notes sạch.
    Trả số ngày đã được dọn dấu vết.
    """
    if not NOTES_FILE.exists():
        return 0
    try:
        raw_lines = NOTES_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0

    records = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"_raw": line})

    import re as _re
    DELETE_WORDS = ("xóa", "xoá", "bỏ ngày", "bỏ task", "delete")

    def _is_task_note(txt: str) -> bool:
        """Ghi chú THẬT (có task/ticket), không phải lệnh xóa."""
        low = txt.lower()
        if any(w in low for w in DELETE_WORDS):
            return False
        if "[DELETED:" in txt:
            return False
        return any(kw in txt.upper() for kw in
                   ("PACS", "DFU", "SDF", "CODING", "UAT", "INVESTIGATION",
                    "ANNUAL", "PUBLIC HOLIDAY", "SPECIAL LEAVE", "NGHỈ"))

    def _delete_target(txt: str, txt_orig: str):
        """Nếu là dấu vết xóa, trả ngày ISO bị nhắm. Không thì None."""
        # Tombstone
        m = _re.search(r'\[DELETED:(\d{4}-\d{2}-\d{2})\]', txt_orig or txt)
        if m:
            return m.group(1)
        m2 = _re.search(r'\[DELETED:(\d{1,2})/(\d{2})/(\d{4})', txt)
        if m2:
            return f"{m2.group(3)}-{m2.group(2)}-{int(m2.group(1)):02d}"
        # Lệnh xóa thuần
        low = txt.lower()
        if any(w in low for w in DELETE_WORDS) and len(txt) < 60 \
                and not _is_task_note(txt):
            md = _re.search(r'(\d{1,2})/(\d{2})/(\d{4})', txt)
            if md:
                return f"{md.group(3)}-{md.group(2)}-{int(md.group(1)):02d}"
        return None

    # Với mỗi dòng dấu vết xóa, tìm xem có ghi chú thật SAU nó (cùng ngày)
    stale_indices = set()
    for i, rec in enumerate(records):
        txt = rec.get("text", "")
        txt_orig = rec.get("text_original") or ""
        target = _delete_target(txt, txt_orig)
        if not target:
            continue
        target_dmy = f"{int(target[8:10])}/{target[5:7]}/{target[0:4]}"
        # Có ghi chú thật về target SAU dòng i không?
        for j in range(i + 1, len(records)):
            jtxt = records[j].get("text", "")
            if (target_dmy in jtxt or target in jtxt) and _is_task_note(jtxt):
                stale_indices.add(i)
                break

    if not stale_indices:
        return 0

    kept = [records[i] for i in range(len(records))
            if i not in stale_indices]
    try:
        tmp = NOTES_FILE.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in kept:
                if "_raw" in rec:
                    f.write(rec["_raw"] + "\n")
                else:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, NOTES_FILE)
        import logging
        logging.getLogger("notes_store").info(
            "cleanup_stale_delete_traces: dọn %d dấu vết xóa lỗi thời.",
            len(stale_indices))
    except OSError:
        return 0
    return len(stale_indices)


def read_notes_between(date_from: date, date_to: date) -> list:
    """Lấy các ghi chú có note_date nằm trong [date_from, date_to]."""
    result = []
    for note in read_all_notes():
        try:
            d = date.fromisoformat(note.get("note_date", ""))
        except ValueError as e:
            log.debug("Bỏ qua ghi chú có note_date không hợp lệ (%s).", e)
            continue
        if date_from <= d <= date_to:
            result.append(note)
    return result


def count_notes_today() -> int:
    """Đếm số ghi chú của riêng hôm nay (để bot báo 'note thứ N')."""
    today = date.today().isoformat()
    return sum(1 for n in read_all_notes() if n.get("note_date") == today)
