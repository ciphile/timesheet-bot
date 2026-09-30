"""
date_normalizer.py — Chuẩn hóa cụm ngày trong ghi chú thành ISO 2026-09-15.

Chỉ xử lý những gì có thể tính CHẮC CHẮN từ ngày gửi (sent_at):
  ✓  "15/09", "15/9", "15-09-2026", "ngày 15 tháng 9"  -> 2026-09-15
  ✓  "hôm nay", "hôm nay là thứ 3"                     -> ngày gửi
  ✓  "hôm qua", "hôm kia"                               -> ngày gửi - 1/2
  ✓  "thứ 3 tuần này", "thứ 4 tuần trước"               -> tính từ sent_at
  ✓  "thứ 3" (không nói tuần nào) -> tuần HIỆN TẠI theo ngày gửi
  ✗  "cả tuần", "tuần trước", "nguyên tuần"             -> GIỮ NGUYÊN
  ✗  "giống tuần trước", "OK gởi đi"                    -> GIỮ NGUYÊN

Nguyên tắc: Thà giữ nguyên còn hơn suy diễn sai.
Không dùng AI — hàm tất định, O(n) theo độ dài text, chạy inline khi
lưu ghi chú vào notes.jsonl.
"""

import re
from datetime import date, timedelta

# Ánh xạ "thứ X" -> weekday (0=Thứ 2, 4=Thứ 6)
_THU_MAP = {
    "hai": 0, "2": 0,
    "ba": 1,  "3": 1,
    "tư": 2,  "4": 2, "tu": 2,
    "năm": 3, "5": 3, "nam": 3,
    "sáu": 4, "6": 4, "sau": 4,
}

def _week_monday(sent: date, last_week: bool = False) -> date:
    """Thứ 2 của tuần chứa sent (hoặc tuần trước nếu last_week)."""
    monday = sent - timedelta(days=sent.weekday())
    if last_week:
        monday -= timedelta(days=7)
    return monday


_LAST_Q = r"(?:tuần\s+)?(?:rồi|trước|qua|vừa\s+rồi)"
_WEEK_Q = r"(?:\s+(?P<q>này|rồi|trước|qua|vừa\s+rồi))?"


def _month_week_days(sent: date, first: bool, prev_month: bool) -> list[date]:
    """Ngày làm việc (T2-T6) của tuần ĐẦU / CUỐI của tháng, CHỈ lấy ngày
    thuộc tháng đó. Tuần đầu = tuần chứa ngày 1 (nếu ngày 1 rơi T7/CN
    thì là tuần kế tiếp). Tuần cuối = tuần chứa ngày cuối tháng."""
    y, m = sent.year, sent.month
    if prev_month:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    first_day = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    last_day = nxt - timedelta(days=1)
    anchor = first_day if first else last_day
    monday = anchor - timedelta(days=anchor.weekday())
    days = [monday + timedelta(days=i) for i in range(5)
            if (monday + timedelta(days=i)).month == m]
    if not days and first:           # ngày 1 là T7/CN → tuần sau
        monday += timedelta(days=7)
        days = [monday + timedelta(days=i) for i in range(5)
                if (monday + timedelta(days=i)).month == m]
    return days


# ── Nhận diện "có nhắc NGÀY CỤ THỂ" (dùng cho luật CHẶT, thêm 24-Sep) ──
DAY_REF_RE = re.compile(
    r"\bthứ\s*(?:[2-7]|hai|ba|tư|tu|bốn|năm|nam|sáu|bảy|bay)\b"
    r"|\bchủ\s*nhật\b|\bcn\b"
    r"|\b\d{1,2}\s*/\s*\d{1,2}\b"
    r"|\bngày\s+\d{1,2}\b"
    r"|\bhôm\s+(?:nay|qua|kia)\b|\bmai\b|\bmốt\b")
COUNT_REF_RE = re.compile(
    r"\b(?:\d+|một|hai|ba|bốn|năm|vài|mấy)\s+(?:ngày|buổi|hôm)\b"
    r"|\bnửa\s+(?:tuần|tháng)\b")
# Phần NGUỒN sau "giống / y như" (vd "... giống thứ 6 tuần trước") KHÔNG tính
_SOURCE_SPLIT_RE = re.compile(r"\b(?:giống|y\s+như|như\s+(?=thứ|ngày|hôm|tuần))")
_UNTIL_RE = re.compile(r"(?:tới|đến|cho\s+tới|cho\s+đến)\s*$")


def _target_part(low: str) -> str:
    """Phần ĐÍCH của câu = trước chữ 'giống' (ngày sau đó là ngày NGUỒN)."""
    m = _SOURCE_SPLIT_RE.search(low)
    return low[:m.start()] if m else low


def _strict_ok(target: str, span: tuple) -> bool:
    """Luật CHẶT: phần đích (bỏ chính cụm vừa khớp) KHÔNG được nhắc ngày cụ
    thể, KHÔNG có "2 ngày / vài buổi / nửa tuần", và chữ "tuần" chỉ 1 lần.
    → "thứ 3 tuần này làm SDF" KHÔNG bao giờ bị hiểu là cả tuần."""
    rest = target[:span[0]] + " " + target[span[1]:]
    if DAY_REF_RE.search(rest) or COUNT_REF_RE.search(target):
        return False
    return len(re.findall(r"\btuần\b", target)) == 1 or "tháng" in target[span[0]:span[1]]


def _month_workdays(y: int, m: int) -> list[date]:
    d, out = date(y, m, 1), []
    while d.month == m:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


_NORMALIZED_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}\s*\((?:thứ|chủ)[^)]*\)", re.IGNORECASE)


def normalize_dates_in_text(text: str, sent: date) -> str:
    """Chuẩn hóa ngày (xem _normalize_dates_once) — KHÔNG LÀM LẠI phần đã chuẩn
    hóa. (Sửa 25-Sep: ghi chú thường bị chuẩn hóa 2 lần — lúc lưu notes và lúc
    bóc tách → '21/09/2026 (thứ Hai) (21/09/2026 (thứ Hai))', mất cụm ngày.)"""
    keep = []

    def _mask(m):
        keep.append(m.group(0))
        return f"\u27e6{chr(65 + len(keep) - 1)}\u27e7"
    masked = _NORMALIZED_RE.sub(_mask, text or "") if len(_NORMALIZED_RE.findall(text or "")) <= 26 else text
    out = _normalize_dates_once(masked, sent)
    for i, v in enumerate(keep):
        out = out.replace(f"\u27e6{chr(65 + i)}\u27e7", v)
    return out


def fix_day_typos(text: str) -> str:
    """Sửa lỗi gõ dấu hay gặp ở tên thứ: 'thử 2' / 'thư 2' / 'thú 2' → 'thứ 2'
    (chỉ khi ngay sau là số 2-7 hoặc chữ hai…bảy). Không đụng 'thử' khác
    ('test thử', 'thử lại')."""
    return re.sub(r"(?i)\bth(?:ử|ư|ú|ự|ừ)\s*(?=(?:[2-7]|hai|ba|tư|năm|sáu|bảy)\b)",
                  "thứ ", text)


def _first_last_n_workdays(sent: date, n: int, first: bool, prev_month: bool) -> list[date]:
    y, m = sent.year, sent.month
    if prev_month:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    days = _month_workdays(y, m)
    return days[:n] if first else days[-n:]


def expand_multi_day_span(text: str, sent: date):
    """Nhận CỤM NHIỀU NGÀY. Trả (list_ngày, (start, end), kiểu) hoặc None.

    NGUYÊN TẮC: KHÔNG CHẮC THÌ KHÔNG BUNG (trả None → AI hiểu câu, và
    note_action còn 1 lớp đối chiếu AI không được tự bung quá tay).
    Chữ "này/rồi/trước" chỉ tính khi đứng NGAY SAU cụm.

    kiểu (dùng quyết định có BẮT xác nhận không — xem note_action):
      month_week  "tuần đầu/cuối (của) tháng (này/trước)"
      to_end      "thứ X / hôm nay / mai  tới hết tuần"     → X..T6
      month       "cả/nguyên/hết/toàn bộ tháng (này/trước/9)"  [luật chặt]
      week        "nguyên/cả/trọn/suốt tuần (này/trước)"   (như trước)
      week_all    "hết/toàn bộ/hết cả tuần (này/trước)"       [luật chặt]
      range       "thứ X tới thứ Y (tuần này/trước)"
      week_bare   "tuần này / tuần trước" ĐỨNG MỘT MÌNH       [luật chặt]
    """
    low = fix_day_typos(text).lower()
    target = _target_part(low)

    # --- N ngày đầu / cuối (tiên / cùng) (của) tháng (này / trước)   (25-Sep)
    m = re.search(r"(?P<n>\d{1,2}|hai|ba|bốn|năm)\s+ngày\s+(?P<pos>đầu|cuối)"
                  r"(?:\s+(?:tiên|cùng))?\s+(?:của\s+)?tháng"
                  r"(?:\s+(?P<mq>này|trước|rồi|vừa\s+rồi))?", target)
    if m:
        nmap = {"hai": 2, "ba": 3, "bốn": 4, "năm": 5}
        n = nmap.get(m.group("n")) or int(m.group("n"))
        if 1 <= n <= 23:
            prev = m.group("mq") in ("trước", "rồi", "vừa rồi")
            days = _first_last_n_workdays(sent, n, m.group("pos") == "đầu", prev)
            return (days, m.span(), "month_first_n") if days else None

    # --- NGÀY tới NGÀY: "15/9 tới 18/9", "21/09/2026 (thứ Hai) tới 23/09/2026
    #     (thứ Tư)" (câu đã chuẩn hóa) → mọi ngày làm việc ở giữa   (25-Sep)
    m = re.search(r"(?P<d1>\d{1,2})/(?P<m1>\d{1,2})(?:/(?P<y1>\d{4}))?(?:\s*\([^)]*\))?"
                  r"\s*(?:tới|đến|->|–|—|-)\s*(?:ngày\s+)?"
                  r"(?P<d2>\d{1,2})/(?P<m2>\d{1,2})(?:/(?P<y2>\d{4}))?(?:\s*\([^)]*\))?",
                  target)
    if m:
        try:
            a = date(int(m.group("y1") or sent.year), int(m.group("m1")), int(m.group("d1")))
            b = date(int(m.group("y2") or m.group("y1") or sent.year), int(m.group("m2")), int(m.group("d2")))
        except ValueError:
            a = b = None
        if a and b and a < b and (b - a).days <= 31:
            days = [a + timedelta(days=i) for i in range((b - a).days + 1)
                    if (a + timedelta(days=i)).weekday() < 5]
            if days:
                return days, m.span(), "range_dates"

    # --- tuần đầu/cuối của tháng
    m = re.search(r"(?:(?:nguyên|cả|trọn|suốt)\s+)?tuần\s+(?P<pos>đầu|cuối)"
                  r"(?:\s+(?:tiên|cùng))?\s+(?:của\s+)?tháng"
                  r"(?:\s+(?P<mq>này|trước|rồi|vừa\s+rồi))?", low)
    if m:
        prev = m.group("mq") in ("trước", "rồi", "vừa rồi")
        days = _month_week_days(sent, m.group("pos") == "đầu", prev)
        return (days, m.span(), "month_week") if days else None

    # --- X tới HẾT tuần  (kiểm TRƯỚC "hết tuần")
    m = re.search(r"(?:từ\s+)?(?:thứ\s*(?P<x>\w+)|(?P<rel>hôm\s+nay|ngày\s+mai|mai))"
                  r"\s*(?:tới|đến|->|–|—|-)\s*hết\s+tuần" + _WEEK_Q, low)
    if m:
        last = (m.group("q") or "này") != "này"
        monday = _week_monday(sent, last_week=last)
        if m.group("x"):
            wx = _THU_MAP.get(m.group("x").strip())
        elif "mai" in m.group("rel"):
            wx = (sent + timedelta(days=1)).weekday() if not last else None
        else:
            wx = sent.weekday() if not last else None
        if wx is None or wx > 4:
            return None
        return ([monday + timedelta(days=i) for i in range(wx, 5)],
                m.span(), "to_end")

    # --- cả tháng [này|trước|9]   (luật CHẶT)
    m = re.search(r"(?:nguyên|cả|trọn|suốt|toàn\s+bộ|hết\s+cả|hết)\s+tháng"
                  r"(?:\s+(?P<mn>\d{1,2})\b)?(?:\s+(?P<mq>này|trước|rồi|vừa\s+rồi))?",
                  target)
    if m and not _UNTIL_RE.search(target[:m.start()]) and _strict_ok(target, m.span()):
        y, mo = sent.year, sent.month
        if m.group("mn"):
            mo = int(m.group("mn"))
            if not 1 <= mo <= 12:
                return None
        elif m.group("mq") in ("trước", "rồi", "vừa rồi"):
            y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
        return _month_workdays(y, mo), m.span(), "month"

    # --- nguyên / cả tuần (như cũ)
    m = re.search(r"(?:nguyên|cả|trọn|suốt)\s+tuần" + _WEEK_Q, low)
    if m:
        last = (m.group("q") or "này") != "này"
        monday = _week_monday(sent, last_week=last)
        return [monday + timedelta(days=i) for i in range(5)], m.span(), "week"

    # --- hết / toàn bộ tuần   (luật CHẶT; "tới hết tuần" không có điểm đầu → không đoán)
    m = re.search(r"(?:hết\s+cả|toàn\s+bộ|hết)\s+tuần" + _WEEK_Q, target)
    if m and not _UNTIL_RE.search(target[:m.start()]) and _strict_ok(target, m.span()):
        last = (m.group("q") or "này") != "này"
        monday = _week_monday(sent, last_week=last)
        return [monday + timedelta(days=i) for i in range(5)], m.span(), "week_all"

    # --- thứ X tới thứ Y (như cũ)
    m = re.search(r"thứ\s*(?P<x>\w+)\s*(?:tới|đến|->|–|—|-)\s*thứ\s*(?P<y>\w+)"
                  r"(?:\s+tuần" + _WEEK_Q + r")?", low)
    if m:
        wx = _THU_MAP.get(m.group("x").strip())
        wy = _THU_MAP.get(m.group("y").strip())
        if wx is not None and wy is not None and wx <= wy:
            last = (m.group("q") or "này") != "này"
            monday = _week_monday(sent, last_week=last)
            return ([monday + timedelta(days=i) for i in range(wx, wy + 1)],
                    m.span(), "range")
        return None

    # --- "tuần này / tuần trước" ĐỨNG MỘT MÌNH   (luật CHẶT NHẤT)
    m = re.search(r"(?<!\w)tuần\s+(?P<q>này|rồi|trước|qua|vừa\s+rồi)(?!\w)", target)
    if m and _strict_ok(target, m.span()):
        last = m.group("q") != "này"
        monday = _week_monday(sent, last_week=last)
        return [monday + timedelta(days=i) for i in range(5)], m.span(), "week_bare"
    return None


def expand_multi_day(text: str, sent: date) -> list[date] | None:
    """Nhận cụm NHIỀU NGÀY, trả list ngày làm việc (T2-T6), hoặc None.
    (Giữ tên cũ cho code đang gọi — logic nằm ở expand_multi_day_span.)"""
    r = expand_multi_day_span(text, sent)
    return r[0] if r else None


# Tháng viết tắt/đầy đủ tiếng Anh (phòng khi người dùng ghi tiếng Anh)
_MON_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _resolve_thu(thu_str: str, sent: date, this_week: bool, last_week: bool) -> date | None:
    """Tính ngày từ 'thứ X tuần này/tuần trước'. Trả None nếu mơ hồ.

    "Tuần trước/rồi" = tuần lịch trước đó (standard "last week").
    Ví dụ: nhắn thứ Bảy 19/9:
      "thứ 4 tuần rồi" = thứ 4 tuần trước = 09/09 (ĐÚNG)
      "thứ 4 tuần này" = thứ 4 tuần này   = 16/09
    """
    key = thu_str.lower().strip()
    wd = _THU_MAP.get(key)
    if wd is None:
        return None
    if this_week:
        monday = sent - timedelta(days=sent.weekday())
        return monday + timedelta(days=wd)
    if last_week:
        monday = sent - timedelta(days=sent.weekday() + 7)
        return monday + timedelta(days=wd)
    return None


def _resolve_date_str(day: int, month: int, year: int | None,
                      sent: date) -> date | None:
    """Tạo date từ ngày/tháng, năm mặc định = năm của sent."""
    y = year if year else sent.year
    # Nếu tháng/ngày hợp lý
    try:
        d = date(y, month, day)
        # Nếu ngày đó trong tương lai hơn 60 ngày so với sent -> sai năm
        if (d - sent).days > 60:
            d = date(y - 1, month, day)
        return d
    except ValueError:  # noqa: BLE001 — ngày không hợp lệ -> trả None, gọi biết
        return None


def _normalize_dates_once(text: str, sent: date) -> str:
    """
    Thay các cụm ngày tường minh trong `text` thành dạng chuẩn
    "DD/MM/YYYY (thứ X)". Chỉ thay những gì tính được chắc chắn.
    Mọi trường hợp mơ hồ GIỮ NGUYÊN để AI xử lý.

    Trả text đã thay thế (hoặc nguyên bản nếu không có gì thay).
    """
    thu_names = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm",
                 "thứ Sáu", "thứ Bảy", "Chủ nhật"]

    def fmt(d: date) -> str:
        return f"{d.strftime('%d/%m/%Y')} ({thu_names[d.weekday()]})"

    # Bước 1: thay tất cả bằng placeholder [D:ISO] trước
    result = text

    # 1a. yyyy-mm-dd
    def sub_iso(m):
        try:   return f"[D:{date.fromisoformat(m.group(0)).isoformat()}]"
        except Exception:  # noqa: BLE001 — ISO không parse được -> giữ nguyên
            return m.group(0)
    result = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', sub_iso, result)

    # 1b-pre. "thứ X DD/MM[/YYYY]" — thứ X chỉ là nhãn, ngày thực = DD/MM
    # Xử lý TRƯỚC bước 1b để tránh bước 1e nhặt lại "thứ X" và tạo ngày trùng
    def sub_thu_plus_dmy(m):
        # groups: 1=DD, 2=MM, 3=YYYY(optional)
        d_val, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else None
        r = _resolve_date_str(d_val, mo, yr, sent)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    result = re.sub(
        r'\bthứ\s+\w+\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?!\d)',
        sub_thu_plus_dmy, result, flags=re.IGNORECASE)

    # 1b-pre2. "thứ X ngày DD/MM" — thứ X đứng TRƯỚC "ngày DD/MM"
    def sub_thu_ngay_dmy(m):
        d_val, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else None
        r = _resolve_date_str(d_val, mo, yr, sent)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    result = re.sub(
        r'\bthứ\s+\w+\s+ngày\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?!\d)',
        sub_thu_ngay_dmy, result, flags=re.IGNORECASE)

    # 1b. dd/mm hoặc dd/mm/yyyy (tránh nhầm mã ticket PACS-123)
    def sub_dmy(m):
        d_val, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else None
        r = _resolve_date_str(d_val, mo, yr, sent)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    # Chỉ match khi có chữ "ngày", "Ngày" hoặc dấu câu/khoảng trắng trước,
    # tránh nhầm "PACS-123" thành ngày
    result = re.sub(
        r'(?<![A-Za-z\-])(\d{1,2})[/](\d{1,2})(?:[/](\d{4}))?(?![\d])',
        sub_dmy, result)

    # 1c. "ngày D tháng M"
    def sub_ngay_thang(m):
        r = _resolve_date_str(int(m.group(1)), int(m.group(2)), None, sent)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    result = re.sub(r'ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})',
                    sub_ngay_thang, result, flags=re.IGNORECASE)

    # 1d. hôm nay / hôm qua / hôm kia
    result = re.sub(r'\bhôm\s+nay\b',
                    f"[D:{sent.isoformat()}]", result, flags=re.IGNORECASE)
    result = re.sub(r'\bhôm\s+qua\b',
                    f"[D:{(sent-timedelta(1)).isoformat()}]",
                    result, flags=re.IGNORECASE)
    result = re.sub(r'\bhôm\s+kia\b',
                    f"[D:{(sent-timedelta(2)).isoformat()}]",
                    result, flags=re.IGNORECASE)

    # 1e. "thứ X tuần này/trước/rồi/vừa rồi/vừa qua/qua"
    def sub_thu_tuan(m):
        thu_str = m.group(1)
        qualifier = (m.group(2) or "").lower()
        # "vừa rồi", "vừa qua", "qua", "rồi", "trước" đều = tuần trước
        last_w = any(x in qualifier for x in
                     ("trước", "rồi", "vừa", "qua"))
        this_w = not last_w
        r = _resolve_thu(thu_str, sent, this_w, last_w)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    result = re.sub(
        r'\bthứ\s+(\w+)(?:\s+(tuần\s+(?:này|trước|rồi|vừa\s+rồi|vừa\s+qua|qua)))?\b',
        sub_thu_tuan, result, flags=re.IGNORECASE)

    # --- 5b. "thứ X" KHÔNG có "tuần" -> mặc định tuần HIỆN TẠI ---
    # Chỉ bắt "thứ X" còn lại (5a đã thay "thứ X tuần..." thành [D:...])
    # Mặc định tuần hiện tại theo ngày gửi — người dùng xác nhận: nếu muốn
    # tuần trước thì sẽ nói "tuần trước".
    def sub_thu_bare(m):
        r = _resolve_thu(m.group(1), sent, this_week=True, last_week=False)
        return f"[D:{r.isoformat()}]" if r else m.group(0)
    # Không match khi "tuần" đứng ngay sau (đã xử lý ở 5a)
    # Không match khi trước là chữ số/chữ (tránh nhầm "PACS-123" hay "số 3")
    result = re.sub(
        r'(?<![\d\w-])thứ\s+(hai|ba|tư|tu|năm|nam|sáu|sau|[23456])(?![\w])',
        sub_thu_bare, result, flags=re.IGNORECASE)

    # Bước 2: expand tất cả [D:ISO] thành dạng đọc được
    # Xử lý "ngày [D:...]" và "Ngày [D:...]" thành "ngày DD/MM/YYYY (thứ X)"
    def expand(m):
        prefix = m.group(1)  # "ngày " hoặc None
        try:
            d = date.fromisoformat(m.group(2))
            label = fmt(d)
            return f"ngày {label}" if prefix else label
        except ValueError:  # noqa: BLE001 — tag không parse được -> giữ nguyên
            return m.group(0)

    result = re.sub(r'(ngày\s+)?\[D:(\d{4}-\d{2}-\d{2})\]',
                    expand, result, flags=re.IGNORECASE)
    return result

def normalize_hours_in_text(text: str) -> str:
    """Chuẩn hóa số giờ: "2 tiếng" -> "2h", "3 giờ" -> "3h", "nửa ngày" -> "4h".
    Giúp AI nhận dạng nhất quán thay vì phải học nhiều cách viết."""
    result = text
    # "N tiếng" / "N giờ" / "Nh" / "N giờ đồng hồ"
    result = re.sub(r'(\d+(?:\.\d+)?)\s*(?:tiếng|giờ(?:\s+đồng\s+hồ)?)',
                    lambda m: f"{m.group(1)}h", result, flags=re.IGNORECASE)
    # "nửa ngày" / "half day" -> 4h
    result = re.sub(r'nửa\s+(?:buổi|ngày)|half\s+day',
                    '4h', result, flags=re.IGNORECASE)
    return result


if __name__ == "__main__":
    # Test nhanh
    from datetime import date
    today = date(2026, 9, 17)  # thứ 4
    tests = [
        ("Ngày 15/09 mình làm ABC",           "ngày 15/09/2026 (thứ 3)"),
        ("Ngày 2026-09-15: nghỉ phép",        "ngày 15/09/2026 (thứ 3)"),
        ("ngày 15 tháng 9 làm DFU",           "ngày 15/09/2026 (thứ 3)"),
        ("hôm qua làm fix bug",               "ngày 16/09/2026 (thứ 4) -> SAI, cần thứ 3"),
        ("thứ 3 tuần này làm ABC",            "ngày 15/09/2026 (thứ 3)"),
        ("thứ 3 tuần trước làm ABC",          "ngày 08/09/2026 (thứ 3)"),
        ("thứ 3 mình làm ABC",               "GIỮ NGUYÊN (mơ hồ)"),
        ("cả tuần này làm PACS-123",          "GIỮ NGUYÊN"),
        ("OK rồi đó gởi đi",                 "GIỮ NGUYÊN"),
        ("hôm nay làm DFU PACSNP-12677",     "ngày 17/09/2026 (thứ 4)"),
    ]
    print(f"Ngày gửi: {today} (thứ 4)\n")
    for text, expected in tests:
        result = normalize_dates_in_text(text, today)
        changed = "→ " + result if result != text else "→ [NGUYÊN BẢN]"
        print(f"  Vào:  {text}")
        print(f"  Ra:   {changed}")
        print(f"  Kỳ:   {expected}")
        print()
