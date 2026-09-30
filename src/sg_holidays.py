"""
sg_holidays.py — Lịch nghỉ lễ Singapore, lấy từ trang MOM.

Nguồn: https://www.mom.gov.sg/employment-practices/public-holidays
(URL đặt trong settings.json, key mom_holidays_url)

Chiến lược (chống bug lấy nhầm năm — trang MOM liệt kê NHIỀU năm):
- Fetch 1 lần mỗi năm; cache riêng từng năm: data\\sg_holidays_<year>.json
- Mỗi ngày trên trang đều ghi kèm năm ("1 January 2026") → parse xong
  kiểm tra chéo: ngày xin cho năm N phải có năm N, lệch là loại.
- CHỈ đọc cột Date của bảng. Cột tên lễ có chú thích "Monday ... will
  be a public holiday" chứa ngày khác — tuyệt đối không parse cột đó.
- Fetch hỏng → dùng cache nếu có; không có cache → báo lỗi rõ ràng,
  KHÔNG đoán.

Rule lễ rơi cuối tuần (người dùng chốt 14-Sep-2026):
- Lễ rơi CHỦ NHẬT  → thứ 2 ngay sau là Public Holiday (tự tính).
- Lễ rơi THỨ 7     → KHÔNG tự sinh gì; người dùng được 1 ngày Special Leave
  tự chọn (bot xử lý riêng, module này chỉ liệt kê các lễ-thứ-7).

Chạy thử trực tiếp:
    python thư mục timesheet\\src\\sg_holidays.py         (năm hiện tại)
    python thư mục timesheet\\src\\sg_holidays.py 2027    (năm chỉ định)
"""

import json
import json
import re
import sys
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

from config_loader import DATA_DIR, load_config
from log_setup import get_logger
from audit_log import audit

log = get_logger("sg_holidays")

FETCH_TIMEOUT_SECONDS = 30

# Trình duyệt giả danh — một số trang chính phủ chặn User-Agent mặc định
# của requests.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )
}

MONTH_NUMBER = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# "1 January 2026", "17 February 2026"...
DATE_PATTERN = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)


class HolidayError(Exception):
    """Lỗi lấy/đọc lịch nghỉ lễ. Thông báo là tiếng Việt."""


def _cache_file(year: int):
    return DATA_DIR / f"sg_holidays_{year}.json"


# ---------------------------------------------------------------------
# Parse HTML trang MOM
# ---------------------------------------------------------------------

def parse_mom_html(html: str) -> dict:
    """Đọc HTML trang MOM, trả về {year: {iso_date: ten_le}} cho MỌI năm
    tìm thấy. Chỉ đọc cột đầu (Date) của từng dòng bảng."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {}

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue  # dòng header (toàn <th>) hoặc dòng lạ

            # Cột Date: có thể chứa 2 ngày (Tết âm 2 ngày liên tiếp)
            date_text = cells[0].get_text(" ", strip=True)
            found = DATE_PATTERN.findall(date_text)
            if not found:
                continue

            # Tên lễ: cột cuối, cắt bỏ từ chữ số đầu tiên trở đi
            # ("New Year's Day1 January 2026, Thursday" -> "New Year's Day")
            name_text = cells[-1].get_text(" ", strip=True)
            m = re.search(r"\d", name_text)
            name = name_text[: m.start()].strip() if m else name_text

            for day_str, month_str, year_str in found:
                y = int(year_str)
                d = date(y, MONTH_NUMBER[month_str.lower()], int(day_str))
                result.setdefault(y, {})[d.isoformat()] = name

    return result


def fetch_from_mom(url: str) -> dict:
    """Tải trang MOM và parse. Trả về {year: {iso_date: ten_le}}."""
    log.info("Fetch lịch nghỉ lễ từ MOM: %s", url)
    try:
        resp = requests.get(url, headers=HTTP_HEADERS,
                            timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HolidayError(
            f"Không tải được trang MOM ({type(e).__name__}: {e}). "
            "Kiểm tra mạng rồi thử lại."
        )

    parsed = parse_mom_html(resp.text)
    if not parsed:
        raise HolidayError(
            "Tải được trang MOM nhưng không parse ra ngày lễ nào — "
            "có thể MOM đã đổi cấu trúc trang. Cần xem lại parser."
        )

    # Kiểm tra chéo từng năm: mọi ngày trong nhóm năm N phải đúng năm N
    for year, days in parsed.items():
        for iso in days:
            if not iso.startswith(str(year)):
                raise HolidayError(
                    f"Parse bất thường: ngày {iso} nằm trong nhóm năm "
                    f"{year}. Không lưu để tránh dữ liệu bẩn."
                )

    log.info("Parse OK: %s",
             ", ".join(f"{y}: {len(d)} ngày" for y, d in sorted(parsed.items())))
    audit("HOLIDAYS_FETCHED",
          ";".join(f"{y}={len(d)}" for y, d in sorted(parsed.items())))
    return parsed


# ---------------------------------------------------------------------
# Cache theo năm
# ---------------------------------------------------------------------

def _save_cache(year: int, holidays: dict) -> None:
    payload = {
        "year": year,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "source": "mom.gov.sg",
        "holidays": holidays,   # {iso_date: ten_le}
    }
    with open(_cache_file(year), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Đã cache %d ngày lễ năm %s vào %s",
             len(holidays), year, _cache_file(year).name)


def _load_cache(year: int):
    path = _cache_file(year)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Cache %s hỏng (%s) — bỏ qua.", path.name, e)
        return None
    # Verify cache đúng năm và ngày bên trong đúng năm
    if payload.get("year") != year:
        log.warning("Cache %s ghi năm %s (xin năm %s) — bỏ qua.",
                    path.name, payload.get("year"), year)
        return None
    holidays = payload.get("holidays", {})
    if any(not iso.startswith(str(year)) for iso in holidays):
        log.warning("Cache %s chứa ngày lệch năm — bỏ qua.", path.name)
        return None
    return holidays


def get_holidays(year: int, config=None, allow_fetch: bool = True) -> dict:
    """Lấy {iso_date: ten_le} của 1 năm. Ưu tiên cache; thiếu thì fetch
    (và nhân tiện cache luôn mọi năm khác trang MOM đang đăng)."""
    cached = _load_cache(year)
    if cached is not None:
        log.debug("Dùng cache lịch lễ năm %s (%d ngày).", year, len(cached))
        return cached

    if not allow_fetch:
        raise HolidayError(
            f"Chưa có cache lịch lễ năm {year} và đang ở chế độ không "
            "fetch. Chạy: python src\\sg_holidays.py để tải."
        )

    if config is None:
        config = load_config()
    parsed = fetch_from_mom(config.get("mom_holidays_url"))

    for y, days in parsed.items():
        _save_cache(y, days)

    if year not in parsed:
        raise HolidayError(
            f"Trang MOM hiện chưa đăng lịch nghỉ lễ năm {year} "
            f"(chỉ có: {', '.join(str(y) for y in sorted(parsed))}). "
            "Thử lại sau khi MOM cập nhật."
        )
    return parsed[year]


# ---------------------------------------------------------------------
# Áp rule cuối tuần cho 1 khoảng ngày
# ---------------------------------------------------------------------

def workday_holidays(date_from: date, date_to: date, config=None,
                     strict: bool = False) -> dict:
    """Trả về {date: ten_le} các ngày NGHỈ LỄ TÍNH VÀO NGÀY LÀM VIỆC
    trong [date_from, date_to], đã áp rule:
    - Lễ Mon–Fri: chính nó.
    - Lễ Chủ nhật: thứ 2 ngay sau (tên lễ + ' (in lieu)').
    - Lễ thứ 7: KHÔNG đưa vào (xem saturday_holidays).
    Tự nạp lịch của MỌI năm mà khoảng ngày chạm tới (vắt năm vẫn đúng).

    LƯỚI AN TOÀN (strict=False, mặc định): năm nào chưa fetch được
    (MOM chưa đăng lịch năm mới, hoặc mạng lỗi) thì năm đó coi như
    KHÔNG có lễ, ghi WARNING, KHÔNG raise — để luồng ghi chú/gửi
    timesheet không bị gãy vì một năm thiếu cache. Hệ quả tệ nhất là
    bỏ lỡ 1 ngày lễ, và validator (check 8h/ngày, 40h/tuần) sẽ tự
    bắt ra vì ngày đó bị hiểu nhầm là ngày làm việc bình thường mà
    không có giờ — bot sẽ hỏi lại, không âm thầm sai.
    strict=True (dùng khi CẦN CHẮC CHẮN, vd đang validate trước khi
    gửi mail thật): raise HolidayError nếu thiếu, không đoán liều.
    """
    result = {}
    for year in range(date_from.year, date_to.year + 1):
        try:
            holidays = get_holidays(year, config=config)
        except HolidayError as e:
            if strict:
                raise
            log.warning("Thiếu lịch nghỉ lễ năm %s (%s) — coi như "
                       "năm đó không có lễ, validator sẽ tự bắt nếu "
                       "ngày lễ bị tính nhầm thành ngày làm việc.",
                       year, e)
            audit("HOLIDAYS_MISSING_FALLBACK", f"{year}: {e}")
            continue
        for iso, name in holidays.items():
            d = date.fromisoformat(iso)
            weekday = d.weekday()          # Mon=0 ... Sun=6
            if weekday <= 4:               # Mon–Fri
                effective, label = d, name
            elif weekday == 6:             # Sunday -> Monday kế tiếp
                effective, label = d + timedelta(days=1), f"{name} (in lieu)"
            else:                          # Saturday -> không tự sinh
                continue
            if date_from <= effective <= date_to:
                result[effective] = label
    return dict(sorted(result.items()))


def saturday_holidays(year: int, config=None) -> list:
    """Các lễ rơi THỨ 7 trong năm — nguồn phát sinh Special Leave.
    Trả về list[(iso_date, ten_le)] theo thứ tự thời gian."""
    holidays = get_holidays(year, config=config)
    result = [
        (iso, name) for iso, name in sorted(holidays.items())
        if date.fromisoformat(iso).weekday() == 5
    ]
    return result


# ---------------------------------------------------------------------
# Bảo đảm lịch năm SAU đã sẵn sàng TRƯỚC KHI bước sang năm mới
# ---------------------------------------------------------------------

# File lưu trạng thái fetch lịch lễ theo năm
_FETCH_STATUS_FILE = DATA_DIR / "holiday_fetch_status.json"


def _load_fetch_status() -> dict:
    try:
        with open(_FETCH_STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Không đọc được holiday_fetch_status.json (%s) — coi như rỗng.", e)
        return {}


def _save_fetch_status(year: int, ok: bool, detail: str) -> None:
    status = _load_fetch_status()
    status[str(year)] = {
        "ok": ok,
        "detail": detail,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        # first_attempt: giữ nguyên lần đầu tiên thất bại,
        # không overwrite -> dùng để tính days_failing chính xác
        "first_attempt_day": 1,  # luôn tính từ 1/12
    }
    tmp = _FETCH_STATUS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    _FETCH_STATUS_FILE.replace(_FETCH_STATUS_FILE) if False else None
    import os; os.replace(tmp, _FETCH_STATUS_FILE)


def ensure_next_year_cached(config=None, today: date = None) -> dict:
    """Gọi mỗi lần bot khởi động (qua housekeeping). Logic:

    - Tháng 1-11: không cần làm gì (lịch năm sau chưa cấp thiết).
    - Tháng 12: kiểm tra cache năm sau. Đã có -> báo OK. Chưa có ->
      thử fetch từ MOM.
    - MOM tèo: ghi nhận thất bại, ngày mai bot bật lại tự thử lại.
      Tự nhiên có ~31 lần thử trong tháng 12 (mỗi ngày 1 lần lúc
      16:00 khi bot bật) — không cần logic retry phức tạp hơn.
    - Sau 7 ngày thất bại liên tiếp: bắt đầu cảnh báo qua Telegram
      để người dùng biết mà can thiệp nếu cần (MOM có thể chưa đăng lịch
      năm sau, hoặc URL đã thay đổi).
    - Thành công: ghi cache + đánh dấu vào holiday_fetch_status.json.
      Các lần tiếp trong tháng 12 thấy "đã thành công" -> bỏ qua.

    Trả {"ok": bool, "year": int, "detail": str, "days_failing": int}.
    KHÔNG raise — lỗi chỉ log, không được block bot khởi động.
    """
    today = today or date.today()
    next_year = today.year + 1

    # Tháng 1-11: chưa cần vội
    if today.month < 12:
        return {"ok": True, "year": next_year,
                "detail": "chưa tới tháng 12, chưa cần vội",
                "days_failing": 0}

    # Đã có cache và đã đánh dấu thành công -> bỏ qua
    cached = _load_cache(next_year)
    status = _load_fetch_status()
    year_status = status.get(str(next_year), {})
    if cached is not None and year_status.get("ok"):
        return {"ok": True, "year": next_year,
                "detail": f"đã có ({len(cached)} ngày, "
                          f"fetch {year_status.get('updated_at','?')[:10]})",
                "days_failing": 0}

    # Số ngày đang thất bại liên tiếp = hôm nay - 1/12 (ngày bắt đầu thử).
    # Đơn giản và luôn chính xác, không phụ thuộc vào file trạng thái.
    days_failing = (today - date(today.year, 12, 1)).days

    # Thử fetch
    try:
        get_holidays(next_year, config=config, allow_fetch=True)
        n_days = len(_load_cache(next_year) or {})
        log.info("Đã fetch lịch nghỉ lễ năm %s (%d ngày).", next_year, n_days)
        audit("HOLIDAYS_NEXT_YEAR_READY",
              f"{next_year}: {n_days} ngày"
              + (f" (sau {days_failing} ngày thất bại)" if days_failing else ""))
        _save_fetch_status(next_year, ok=True,
                           detail=f"{n_days} ngày từ MOM")
        return {"ok": True, "year": next_year,
                "detail": f"fetch OK ({n_days} ngày)",
                "days_failing": 0}

    except HolidayError as e:
        days_failing += 1  # cộng thêm ngày hôm nay
        msg = (f"Chưa fetch được lịch năm {next_year} "
               f"(thử {days_failing} ngày, lỗi: {e}). "
               "Bot tự thử lại lúc 16:00 mỗi ngày.")
        if days_failing >= 7:
            msg += (f" Đã {days_failing} ngày chưa được — "
                    "có thể MOM chưa đăng lịch năm sau hoặc URL đổi.")
        log.warning(msg)
        audit("HOLIDAYS_FETCH_FAILED",
              f"{next_year}: ngày {days_failing}: {e}")
        _save_fetch_status(next_year, ok=False,
                           detail=f"lần {days_failing}: {e}")
        return {"ok": False, "year": next_year, "detail": str(e),
                "days_failing": days_failing}


# ---------------------------------------------------------------------
# Housekeeping: dọn cache NĂM ĐÃ QUA (không đụng năm hiện tại/tới)
# ---------------------------------------------------------------------

def prune_old_caches(keep_years_back: int = 2, today: date = None) -> int:
    """Xóa file sg_holidays_<year>.json của những năm đã qua LÂU
    (mặc định giữ 2 năm trước, đủ để tra cứu/đối chiếu lịch sử).
    KHÔNG BAO GIỜ xóa năm hiện tại hoặc năm sau. Trả số file đã xóa."""
    today = today or date.today()
    cutoff_year = today.year - keep_years_back
    removed = 0
    for path in DATA_DIR.glob("sg_holidays_*.json"):
        try:
            year = int(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            log.debug("Tên file cache lịch lễ lạ, bỏ qua: %s", path.name)
            continue
        if year < cutoff_year:
            path.unlink()
            removed += 1
            log.info("Đã dọn cache lịch lễ năm %s (quá cũ).", year)
    return removed


# ---------------------------------------------------------------------
# Self-test: in lịch 1 năm ra màn hình
# ---------------------------------------------------------------------
if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    print(f"Lịch nghỉ lễ Singapore năm {year} (nguồn MOM):")
    print("-" * 55)
    try:
        holidays = get_holidays(year)
    except HolidayError as e:
        print("LỖI:", e)
        sys.exit(1)

    for iso, name in sorted(holidays.items()):
        d = date.fromisoformat(iso)
        weekday = d.strftime("%A")
        note = ""
        if d.weekday() == 6:
            note = "  -> thứ 2 kế tiếp là Public Holiday"
        elif d.weekday() == 5:
            note = "  -> SPECIAL LEAVE tự chọn (lễ rơi thứ 7)"
        print(f"{iso}  {weekday:<9}  {name}{note}")
    print("-" * 55)
    print(f"Tổng: {len(holidays)} ngày. Cache: {_cache_file(year)}")
