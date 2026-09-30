"""
daily_store.py — Kho kết quả PARSE THEO NGÀY (data\\parsed_days.json).

Mỗi khi người dùng nhắn ghi chú, bot parse lại TOÀN BỘ ghi chú của ngày đó
và cất kết quả ở đây. Tối thứ 6, orchestrator dùng lại kết quả đã
chốt này thay vì gọi AI lại → nhất quán với cái người dùng đã xác nhận
trong ngày, và tiết kiệm lượt AI.

Cấu trúc:
    {"2026-09-15": {"parsed_at": "...", "entries": [ ... ]}, ...}

- Chỉ cache NGÀY SẠCH (AI parse ra đủ, không còn câu hỏi). Ngày còn
  vướng -> không cache -> thứ 6 hỏi lại như thường.
- entries lưu dạng JSON (date là chuỗi ISO); đọc ra thành date thật.
- Ngày đã gửi cho sếp vẫn giữ lại (nhẹ, và tiện đối chiếu); dọn bằng
  prune_before() nếu sau này file phình.
"""

import json
import os
from datetime import date, datetime

from config_loader import DATA_DIR
from log_setup import get_logger

log = get_logger("daily_store")

PARSED_FILE = DATA_DIR / "parsed_days.json"


def _dup_key_hook(pairs):
    """object_pairs_hook: phát hiện KEY NGÀY TRÙNG trong JSON.
    json.load bình thường âm thầm giữ key cuối, bỏ key đầu → MẤT DỮ
    LIỆU không ai biết. Hook này log cảnh báo khi thấy key trùng, và
    vẫn giữ key cuối (không thể giữ cả 2 trong dict) — nhưng ít nhất
    có LOG để người dùng biết file bị trùng ngày mà sửa."""
    seen = {}
    dups = []
    for k, v in pairs:
        if k in seen:
            dups.append(k)
        seen[k] = v
    if dups:
        log.error("parsed_days.json có KEY NGÀY TRÙNG: %s — json chỉ "
                  "giữ bản CUỐI mỗi ngày, các bản trước BỊ MẤT. Kiểm tra "
                  "file, mỗi ngày chỉ được có 1 lần.", ", ".join(sorted(set(dups))))
    return seen


# Cờ để checkpoint biết file vừa đọc có key trùng (validate sẽ báo)
_last_load_had_dup = {"dups": []}


def _load() -> dict:
    if not PARSED_FILE.exists():
        return {}
    try:
        raw = PARSED_FILE.read_text(encoding="utf-8")
        # Đọc bằng hook phát hiện key trùng
        _last_load_had_dup["dups"] = []
        def _hook(pairs):
            seen = {}
            for k, v in pairs:
                if k in seen and len(k) == 10 and k[4] == "-":
                    # key dạng ngày YYYY-MM-DD bị trùng
                    _last_load_had_dup["dups"].append(k)
                seen[k] = v
            return seen
        data = json.loads(raw, object_pairs_hook=_hook)
        if _last_load_had_dup["dups"]:
            log.error("parsed_days.json KEY NGÀY TRÙNG: %s — json giữ bản "
                      "CUỐI, bản trước MẤT. Mỗi ngày chỉ được 1 lần!",
                      ", ".join(sorted(set(_last_load_had_dup["dups"]))))
        return data
    except json.JSONDecodeError as e:
        # FILE HỎNG (máy tắt giữa lúc ghi, sửa tay sai dấu phẩy...).
        # Trước 24-Sep: coi như rỗng → lần save_day kế tiếp GHI ĐÈ file chỉ
        # còn 1 ngày → MẤT HẾT. Nay: CẤT file hỏng sang tên khác trước, để
        # dữ liệu cũ còn đó mà khôi phục (xem backup\parsed_days\).
        from datetime import datetime as _dt
        from config_loader import CORRUPT_DIR
        CORRUPT_DIR.mkdir(parents=True, exist_ok=True)
        bad = CORRUPT_DIR / f"parsed_days.json.corrupt_{_dt.now():%Y%m%d_%H%M%S}"
        try:
            os.replace(PARSED_FILE, bad)
            where = bad.name
        except OSError as e2:
            where = f"(cất thất bại: {e2})"
        log.error("parsed_days.json HỎNG (%s) — đã cất sang %s. Bot tạm coi "
                  "như rỗng. KHÔI PHỤC: chép bản mới nhất trong "
                  "data\\backup\\parsed_days_daily\\ về data\\parsed_days.json.", e, where)
        try:
            from audit_log import audit
            audit("PARSED_DAYS_CORRUPT", f"cất sang {where}: {e}")
        except Exception:  # noqa: BLE001
            pass
        return {}
    except OSError as e:
        log.warning("Không đọc được parsed_days.json (%s) — coi như rỗng.", e)
        return {}


def last_load_duplicate_days() -> list:
    """Trả danh sách ngày bị key trùng ở lần _load gần nhất (rỗng = ok).
    Checkpoint validation dùng để báo lỗi rõ cho người dùng."""
    return sorted(set(_last_load_had_dup.get("dups", [])))


def _save(data: dict) -> None:
    """Ghi ATOMIC (tmp + os.replace): máy tắt đột ngột giữa lúc ghi
    sẽ không bao giờ để lại file JSON nửa-ghi/hỏng."""
    tmp = PARSED_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PARSED_FILE)


def load_all() -> dict:
    """Trả toàn bộ parsed_days dưới dạng {day_str: day_data}.
    Dùng bởi /summary và /summaryweek — không gọi AI."""
    data = _load()
    return dict(sorted(data.items()))


def save_day(day: date, entries: list) -> None:
    """Ghi đè kết quả parse của 1 ngày (parse lại cả ngày mỗi lần).

    Lưu kèm "summary": dòng tóm tắt dễ đọc bằng mắt, để mở file ra là
    thấy ngay ngày đó task nào mấy giờ, không phải dò JSON.
    """
    data = _load()
    summary = "; ".join(
        f"{e['hours']:g}h {e['task']} — {e['project']}"
        for e in sorted(entries, key=lambda x: x["task"]))
    total = sum(float(e["hours"]) for e in entries)
    data[day.isoformat()] = {
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{summary}  (tổng {total:g}h)" if entries else "(trống)",
        "entries": [{**e, "date": e["date"].isoformat()} for e in entries],
    }
    _save(data)
    log.info("Đã cache parse ngày %s: %d dòng.", day, len(entries))


def forget_day(day: date) -> None:
    """Xóa cache 1 ngày (khi ngày đó trở nên mơ hồ, cần hỏi lại)."""
    data = _load()
    if data.pop(day.isoformat(), None) is not None:
        _save(data)
        log.info("Đã bỏ cache parse ngày %s.", day)


def entries_for_days(days: list) -> tuple:
    """Trả (entries, days_có_cache) cho danh sách ngày cần."""
    data = _load()
    entries, covered = [], []
    for d in days:
        record = data.get(d.isoformat())
        if not record:
            continue
        covered.append(d)
        for e in record["entries"]:
            entries.append({**e, "date": date.fromisoformat(e["date"])})
    return entries, covered


def prune_before(day: date) -> int:
    """Dọn cache cũ hơn 1 mốc. Trả số ngày đã dọn."""
    data = _load()
    old = [k for k in data if k < day.isoformat()]
    for k in old:
        data.pop(k)
    if old:
        _save(data)
    return len(old)
