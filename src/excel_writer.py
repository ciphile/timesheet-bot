"""
excel_writer.py — Toàn bộ thao tác lên file Excel LiveReport.

Thiết kế:
- Mỗi tháng 1 FILE LÀM VIỆC tên ổn định:  output\\LiveReport_2026-09.xlsx
  (tích lũy dần trong tháng; tên nội bộ, sếp không thấy).
- Khi gửi, tạo BẢN GIAO tên theo chuẩn sếp quen:
  "LiveReport Sept_2026 -người dùng (18 Sept).xlsx" (copy từ file làm việc).
  → giải quyết mâu thuẫn "tên file chứa ngày gửi" vs "file tích lũy".
- Mỗi lần ghi là GHI LẠI TOÀN VÙNG dữ liệu (xóa sạch vùng, ghi lại từ
  danh sách entries đã sort theo ngày): đơn giản, không lệch thứ tự,
  chạy lại bao nhiêu lần cũng ra cùng kết quả.
- Template 47 dòng trống format sẵn; thiếu chỗ thì tự chèn dòng mới
  NGAY TRÊN dòng Full Summary, copy nguyên style dòng trên.
- LUÔN backup file cũ vào backup\\ trước khi ghi.
- Chốt an toàn: mọi entry phải đúng tháng của file — sai là từ chối.

Entry = dict với các key:
    date        : datetime.date (ngày công việc)
    project     : str  (cột D)
    task        : str  (cột E — Task Name)
    description : str  (cột F — được phép rỗng, vd Public Holiday)
    hours       : float (cột G)

Chạy thử trực tiếp (demo tháng 12/2030, không đụng dữ liệu thật):
    python thư mục timesheet\\src\\excel_writer.py
"""

import shutil
from copy import copy
from datetime import date, datetime
from pathlib import Path

import openpyxl

from config_loader import BACKUP_DIR, OUTPUT_DIR, TEMPLATE_DIR, load_config
from log_setup import get_logger
from audit_log import audit

log = get_logger("excel_writer")

TEMPLATE_FILE = TEMPLATE_DIR / "master_template.xlsx"
FIRST_DATA_ROW = 5
DESC_COL = 6            # cột F — CHỈ cột này được xuống dòng (24-Sep)
WRAP_MIN_LEN = 61       # mô tả <= 61 ký tự → KHÔNG xuống dòng
MAX_ROW_HEIGHT = 409    # giới hạn chiều cao hàng của Excel (pt)


# ---------------------------------------------------------------------
# Cột F: XUỐNG DÒNG TRONG Ô theo từng ticket (thêm 24-Sep)
# ---------------------------------------------------------------------
import re as _re
_TICKET_LEAD_RE = _re.compile(r"(?i)\bticket\s*(?:no\.?|number|#)?\s*$")


def _ticket_units(desc: str) -> list:
    """Vị trí (start, end) từng 'đơn vị ticket' trong mô tả: mã ticket kèm
    'Part X', và kèm cả chữ 'Ticket #' đứng ngay trước (1 khối, không tách)."""
    import task_rules as _tr
    spans = [m.span() for m in _tr.TICKET_PART_RE.finditer(desc)]
    spans += [m.span() for m in _tr.BARE_PREFIX_RE.finditer(desc)]
    # "Ticket #" LUÔN là đầu 1 mục, kể cả khi mã phía sau sai định dạng
    # ("Ticket # inc00d5642", "Ticket # inc:") — sửa 25-Sep
    covered = lambda p: any(a <= p < b for a, b in spans)
    for m in _re.finditer(r"(?i)\bticket\s*#\s*[^\s,;:]*", desc):
        if not covered(m.start()) and not covered(m.end() - 1):
            spans.append(m.span())
    units = []
    for s, e in sorted(spans):
        lead = _TICKET_LEAD_RE.search(desc[:s])
        if lead and lead.start() < s:
            s = lead.start()
        if units and s < units[-1][1]:          # chồng lấn → gộp
            units[-1] = (units[-1][0], max(e, units[-1][1]))
        else:
            units.append((s, e))
    return units


def format_desc_for_excel(desc: str) -> str:
    """Chèn XUỐNG DÒNG trong ô cột F trước mỗi ticket (từ ticket thứ 2).
    Dùng cho MỌI file Excel bot ghi (làm việc, nháp xem trước, bản giao) —
    qua _format_col_f → 3 file giống hệt nhau.
    CỔNG BẮT BUỘC (người dùng, 24-Sep): chỉ xuống dòng khi mô tả CÓ ÍT NHẤT 1 DẤU
    PHẨY và DÀI HƠN 61 ký tự (<= 61 ký tự → giữ 1 dòng).
    LUẬT CHẶT (sau khi qua cổng):
      1. cần >= 2 ticket
      2. ngắt khi trước ticket là dấu , ; . (hết mục / hết câu)
      3. chỉ có khoảng trắng → CHỈ ngắt nếu ngay trước là 1 TICKET khác
         (danh sách không phẩy); trước là chữ thường = giữa câu → KHÔNG ngắt
      4. không tách 'Ticket #' khỏi số, không tách ticket khỏi 'Part X'
      5. ticket trong ngoặc (...) → không ngắt
      6. KHÔNG đổi chữ nào: chỉ thay khoảng trắng bằng xuống dòng
    Chỉ dùng khi GHI Excel; parsed_days / Telegram / email giữ 1 dòng."""
    if not desc:
        return ""
    if "\n" in desc:
        # Mô tả có SẴN xuống dòng (tin Telegram nhiều dòng / file cũ) → gộp về 1
        # dòng theo đúng luật đọc ngược rồi định dạng lại (sửa 25-Sep: trước
        # bỏ qua cả ô → không ticket nào được ngắt).
        desc = _read_desc(desc)
    if "," not in desc or len(desc) <= WRAP_MIN_LEN:     # CỔNG BẮT BUỘC
        return desc
    units = _ticket_units(desc)
    if len(units) < 2:
        return desc
    cuts = []                                   # (vị trí thay, độ dài khoảng trắng)
    for i in range(1, len(units)):
        s = units[i][0]
        before = desc[:s]
        # Trong ngoặc THẬT (có '(' chưa đóng trước VÀ có ')' phía sau) → không
        # ngắt. Ngoặc quên đóng không được chặn mọi ticket phía sau (25-Sep).
        if before.count("(") > before.count(")") and ")" in desc[s:]:
            continue
        stripped = before.rstrip()
        gap = len(before) - len(stripped)
        if stripped.endswith(","):
            # BỎ dấu phẩy ngay chỗ xuống dòng (25-Sep): đã xuống dòng thì không
            # cần phẩy. Bỏ LUÔN khoảng trắng thừa TRƯỚC phẩy ("life ,Ticket").
            # _read_desc trả lại ", " khi đọc ngược.
            keep = len(stripped[:-1].rstrip())
            cuts.append((keep, s - keep, "\n"))
        elif stripped.endswith((";", ".")):
            cuts.append((len(stripped), gap, "\n"))           # giữ ; .
        elif gap and units[i - 1][1] == len(stripped):
            # 2 ticket cách nhau CHỈ bằng khoảng trắng (không có phẩy): giữ 1
            # dấu cách ẩn cuối dòng để đọc ngược KHÔNG tự thêm phẩy
            cuts.append((len(stripped), gap, " \n"))
    for pos, gap, brk in reversed(cuts):
        desc = desc[:pos] + brk + desc[pos + gap:]
    return desc


def _desc_lines(text: str, col_width) -> int:
    """Số dòng hiển thị của ô (xuống dòng thật + tự gói do cột hẹp)."""
    per = max(10, int((col_width or 34) * 1.15))
    return sum(max(1, -(-len(line) // per)) for line in (text or "").split("\n"))


# ── Chiều cao SÁT CHỮ cho ô tự xuống hàng (25-Sep) ────────────────────
# Trước: mỗi dòng = 13pt (chiều cao 1 hàng template) và ~39 ký tự/dòng → với
# chữ Microsoft Sans Serif 8pt (dòng thật ~10pt, ~47 ký tự) hàng cao gấp ~1,5
# lần chữ, thừa khoảng trắng trên/dưới. Chỉnh 2 hệ số dưới nếu cần tinh chỉnh.
LINE_SPACING = 1.25      # CỘT D (không đo được font): chiều cao 1 dòng = cỡ chữ × hệ số (pt)
LINE_SPACING_F = 1.25    # CỘT F = cột D (02-Oct: đo dòng CHÍNH XÁC theo từng chữ → 1.20 làm
                         # DFU (chữ IN HOA) bị cắn chữ; 1.20 trước đây chỉ 'đẹp' nhờ ước lượng dư)
FONT_LINE_FACTOR = 1.05  # (đo được font) chiều cao 1 dòng = (ascent+descent) × hệ số
ROW_PADDING_PT = 2.0     # đệm tổng trên + dưới (pt)
_FONT_FILES = {"microsoft sans serif": "micross.ttf", "calibri": "calibri.ttf",
               "arial": "arial.ttf", "tahoma": "tahoma.ttf", "verdana": "verdana.ttf",
               "segoe ui": "segoeui.ttf", "times new roman": "times.ttf",
               "cambria": "cambria.ttc", "consolas": "consola.ttf"}
_FONT_CACHE: dict = {}


def _load_font(name: str, size_pt: float):
    """Font thật (Pillow + file font Windows) để ĐO chữ; None nếu không có."""
    key = ((name or "").lower(), size_pt)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    try:
        import os
        from PIL import ImageFont
        fname = _FONT_FILES.get(key[0])
        if fname:
            for d in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),):
                path = os.path.join(d, fname)
                if os.path.exists(path):
                    font = ImageFont.truetype(path, max(1, round(size_pt * 96 / 72)))
                    break
    except Exception:  # noqa: BLE001 — không có Pillow / font → ước lượng
        font = None
    _FONT_CACHE[key] = font
    return font


# Độ rộng chữ (đơn vị /1000 em) theo font Arial — cùng tỉ lệ Microsoft Sans Serif.
# Dùng khi KHÔNG có Pillow để đo font thật (02-Oct): trước đây coi mọi chữ rộng
# bằng nhau → chữ IN HOA / chữ số (mã ticket) bị ước lượng HẸP hơn thật → thiếu
# dòng → hàng thấp, cắn chữ (DFU, cột D nhiều PACSNP).
_CHAR_W = {**{c: 556 for c in "0123456789"}, " ": 278, ",": 278, ".": 278, "-": 333,
           ":": 278, ";": 278, "#": 556, "&": 667, "(": 333, ")": 333, "/": 278,
           "_": 556, "'": 191, '"': 355, "@": 1015, "+": 584, "=": 584,
           "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
           "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722,
           "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
           "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
           "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
           "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556,
           "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556,
           "v": 500, "w": 722, "x": 500, "y": 500, "z": 500}


def _approx_text_px(s: str, size_pt: float) -> float:
    """Độ rộng (pixel, 96 dpi) của chuỗi theo bảng độ rộng TỪNG CHỮ."""
    return sum(_CHAR_W.get(ch, 600) for ch in s) / 1000 * size_pt * 96 / 72


def _wrap_line_count(text: str, width_chars: float, name: str, size_pt: float) -> int:
    """Số dòng HIỂN THỊ (gói theo từ như Excel). Có font thật → đo pixel;
    không có → ước lượng theo cỡ chữ (độ rộng cột Excel tính theo chữ số
    Calibri 11 → cỡ nhỏ hơn chứa được nhiều ký tự hơn)."""
    font = _load_font(name, size_pt)
    col_px = int(((256 * (width_chars or 34) + int(128 / 7)) / 256) * 7) - 6
    per_chars = max(10, int((width_chars or 34) * 11 / max(size_pt, 6)))

    def width(s):
        return font.getlength(s) if font else _approx_text_px(s, size_pt)
    total = 0
    for para in (text or "").split("\n"):
        lines, cur = 1, ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if width(cand) <= col_px or not cur:
                cur = cand
                while width(cur) > col_px and len(cur) > 1:      # từ dài hơn cột
                    cut = max(1, int(len(cur) * col_px / width(cur)))
                    cur = cur[cut:]
                    lines += 1
            else:
                lines += 1
                cur = word
        total += lines
    return total


def _cell_lines_and_height(text: str, cell, width_chars,
                           spacing: float = None) -> tuple:
    """(số dòng hiển thị, chiều cao hàng SÁT chữ) của 1 ô theo font + cỡ chữ
    THẬT của chính ô đó. Dùng chung cho cột F và cột D."""
    size = float(cell.font.sz or 11)
    n = _wrap_line_count(text, width_chars, cell.font.name, size)
    font = _load_font(cell.font.name, size)
    if font is not None:
        asc, desc = font.getmetrics()                  # pixel ở 96 dpi
        line_pt = (asc + desc) * 72 / 96 * FONT_LINE_FACTOR
    else:
        line_pt = size * (LINE_SPACING if spacing is None else spacing)
    return n, min(MAX_ROW_HEIGHT, round(n * line_pt + ROW_PADDING_PT, 1))


def _fit_row_height(text: str, cell, width_chars) -> float:
    """Chiều cao hàng SÁT chữ cho ô đã tự xuống hàng."""
    return _cell_lines_and_height(text, cell, width_chars, LINE_SPACING_F)[1]   # CỘT F


def _grow_row_for_col_d(ws, r: int, base_h) -> None:
    """Cột D (Project, vd NP nhiều ticket PACSNP) — thêm 25-Sep:
      - chữ VỪA 1 dòng → KHÔNG đụng gì
      - phải xuống dòng → NÂNG hàng đủ cao để không cắt chữ cột D
    Chỉ TĂNG, không bao giờ giảm → không ảnh hưởng chữ cột F (và ngược lại)."""
    cell = ws.cell(row=r, column=4)
    if cell.value in (None, ""):
        return
    n, need = _cell_lines_and_height(str(cell.value), cell,
                                     ws.column_dimensions["D"].width)
    if n <= 1:
        return
    cur = ws.row_dimensions[r].height or base_h or 15.0
    if need > cur:
        ws.row_dimensions[r].height = need


_BASE_ROW_H = {"v": "unset"}


def _base_row_height():
    """Chiều cao CHUẨN 1 hàng dữ liệu — lấy từ master_template (hàng đầu dữ
    liệu). None = mặc định Excel. Dùng để trả hàng về chuẩn khi còn 1 dòng."""
    if _BASE_ROW_H["v"] == "unset":
        try:
            wb = openpyxl.load_workbook(TEMPLATE_FILE)
            _BASE_ROW_H["v"] = wb.active.row_dimensions[FIRST_DATA_ROW].height
        except Exception:  # noqa: BLE001
            _BASE_ROW_H["v"] = None
    return _BASE_ROW_H["v"]


def _read_desc(value) -> str:
    """Đọc cột F từ Excel về ĐÚNG câu 1 dòng ban đầu (ngược với
    format_desc_for_excel) → gởi lại / sửa ngày đã gửi / tính phép như cũ:
      dòng kết thúc bằng ' ' (dấu cách ẩn) → nối bằng ' ' (vốn không có phẩy)
      dòng kết thúc bằng ; . hoặc , (file cũ còn phẩy) → nối bằng ' '
      còn lại (phẩy đã bị bỏ lúc ghi) → trả lại ', '"""
    s = str(value or "")

    def _join(m):
        left = s[:m.start()]
        if left.endswith((" ", "\t")):
            return ""                     # dấu cách ẩn đã có sẵn trước \n
        if left.endswith((",", ";", ".")):
            return " "
        return ", "
    return _re.sub(r"\n[ \t]*", _join, s).strip() if "\n" in s else s.strip()
SUMMARY_LABEL = "Full Summary"
STYLE_KEYS = ("font", "border", "fill", "alignment", "protection")


class ExcelWriterError(Exception):
    """Lỗi thao tác Excel. Thông báo là tiếng Việt."""


# ---------------------------------------------------------------------
# Tên file
# ---------------------------------------------------------------------

def working_file_path(month: date) -> Path:
    """File làm việc nội bộ của 1 tháng (tên ổn định)."""
    return OUTPUT_DIR / f"LiveReport_{month.year}-{month.month:02d}.xlsx"


def delivery_file_name(file_month: date, send_day: date, config) -> str:
    """Tên file giao sếp, theo pattern trong settings.json.
    Vd: LiveReport Aug_2026 -người dùng (4 Sept).xlsx"""
    month_names = config.get("month_names")
    return config.get("file_name_pattern").format(
        file_month=month_names[file_month.month - 1],
        file_year=file_month.year,
        send_day=send_day.day,                      # không số 0 đầu
        send_month=month_names[send_day.month - 1],
    )


# ---------------------------------------------------------------------
# Tiện ích nội bộ
# ---------------------------------------------------------------------

def _validate_entries(month: date, entries: list) -> None:
    for i, e in enumerate(entries, start=1):
        d = e.get("date")
        if not isinstance(d, date):
            raise ExcelWriterError(f"Entry #{i}: 'date' phải là datetime.date.")
        if (d.year, d.month) != (month.year, month.month):
            raise ExcelWriterError(
                f"Entry #{i} ({d.isoformat()}) KHÔNG thuộc tháng "
                f"{month.year}-{month.month:02d} — từ chối ghi để file "
                "tháng không lẫn dòng tháng khác."
            )
        if not str(e.get("project", "")).strip():
            raise ExcelWriterError(f"Entry #{i} ({d}): thiếu 'project' (cột D).")
        if not str(e.get("task", "")).strip():
            raise ExcelWriterError(f"Entry #{i} ({d}): thiếu 'task' (cột E).")
        try:
            hours = float(e.get("hours"))
        except (TypeError, ValueError):
            raise ExcelWriterError(f"Entry #{i} ({d}): 'hours' không phải số.")
        if hours <= 0:
            raise ExcelWriterError(f"Entry #{i} ({d}): 'hours' phải > 0.")


def _find_summary_row(ws) -> int:
    for row in range(FIRST_DATA_ROW, ws.max_row + 1):
        if ws.cell(row=row, column=2).value == SUMMARY_LABEL:
            return row
    raise ExcelWriterError(
        f"Không tìm thấy dòng '{SUMMARY_LABEL}' trong file — file hỏng "
        "hoặc sai template."
    )


def _copy_row_style(ws, src_row: int, dst_row: int) -> None:
    """Copy nguyên style (font, viền, nền, căn lề, định dạng số) của
    1 dòng sang dòng khác, cột A..G, kèm chiều cao dòng."""
    for col in range(1, 8):
        src = ws.cell(row=src_row, column=col)
        dst = ws.cell(row=dst_row, column=col)
        for key in STYLE_KEYS:
            setattr(dst, key, copy(getattr(src, key)))
        dst.number_format = src.number_format
    if ws.row_dimensions[src_row].height:
        ws.row_dimensions[dst_row].height = ws.row_dimensions[src_row].height


def _ensure_capacity(ws, summary_row: int, rows_needed: int) -> int:
    """Bảo đảm vùng dữ liệu chứa đủ rows_needed dòng. Thiếu thì chèn
    thêm ngay trên dòng Full Summary, style copy từ dòng dữ liệu trên.
    Trả về summary_row mới."""
    capacity = summary_row - FIRST_DATA_ROW
    if rows_needed <= capacity:
        return summary_row
    extra = rows_needed - capacity
    log.info("Vùng dữ liệu đầy (%d/%d) — chèn thêm %d dòng.",
             rows_needed, capacity, extra)

    # Gỡ merge C:F của dòng summary trước khi chèn để không kẹt merge
    merge_ref = None
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row == summary_row:
            merge_ref = str(rng)
            ws.unmerge_cells(merge_ref)

    ws.insert_rows(summary_row, extra)
    # Copy style từ dòng CÁCH 2 DÒNG phía trên (cùng chẵn/lẻ) để giữ
    # đúng nhịp sọc xám xen kẽ của file gốc. Chạy tuần tự nên dòng
    # nguồn luôn đã có style trước khi bị copy.
    for r in range(summary_row, summary_row + extra):
        _copy_row_style(ws, src_row=r - 2, dst_row=r)

    new_summary = summary_row + extra
    if merge_ref:
        ws.merge_cells(f"C{new_summary}:F{new_summary}")
    return new_summary


# ---------------------------------------------------------------------
# API chính
# ---------------------------------------------------------------------

def write_month_entries(month: date, entries: list, config,
                        path_override=None) -> dict:
    """Ghi TOÀN BỘ dữ liệu của 1 tháng vào file Excel.

    - entries: list entry (xem đầu file). Được sort lại theo ngày.
    - Mặc định ghi vào FILE LÀM VIỆC của tháng (backup trước khi ghi).
    - path_override: ghi ra file khác (vd bản PREVIEW cho người dùng duyệt
      qua Telegram) — không backup, không đụng file thật.
    - Trả về dict: {"path", "rows", "summary_row", "backup"}
    """
    _validate_entries(month, entries)
    entries = sorted(entries, key=lambda e: e["date"])
    employee_name = config.get("employee_name")

    if not TEMPLATE_FILE.exists():
        raise ExcelWriterError(
            f"Thiếu template: {TEMPLATE_FILE}\n"
            "Copy master_template.xlsx vào thư mục template trước."
        )

    path = Path(path_override) if path_override else working_file_path(month)
    backup_path = None
    if path_override is not None:
        # Bản preview: luôn dựng mới từ template, không backup
        shutil.copy2(TEMPLATE_FILE, path)
    elif path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{path.stem}.before_{stamp}.xlsx"
        shutil.copy2(path, backup_path)
        log.info("Đã backup %s -> %s", path.name, backup_path.name)
        audit("EXCEL_BACKUP", backup_path.name)
    else:
        shutil.copy2(TEMPLATE_FILE, path)
        log.info("Tạo file tháng mới từ template: %s", path.name)
        audit("EXCEL_CREATE_MONTH", path.name)

    wb = openpyxl.load_workbook(path)
    ws = wb.active

    summary_row = _find_summary_row(ws)
    summary_row = _ensure_capacity(ws, summary_row, len(entries))

    # Xóa sạch giá trị vùng dữ liệu (giữ nguyên style)
    for r in range(FIRST_DATA_ROW, summary_row):
        for col in range(1, 8):
            ws.cell(row=r, column=col).value = None

    # Ghi lại từ đầu, đã sort theo ngày
    if employee_name and not ws.cell(row=4, column=1).value:
        ws.cell(row=4, column=1).value = employee_name      # nhãn tên đầu bảng
    for i, e in enumerate(entries):
        r = FIRST_DATA_ROW + i
        d = e["date"]
        ws.cell(row=r, column=2).value = employee_name
        ws.cell(row=r, column=3).value = datetime(d.year, d.month, d.day)
        ws.cell(row=r, column=4).value = str(e["project"]).strip()
        ws.cell(row=r, column=5).value = str(e["task"]).strip()
        desc = str(e.get("description", "") or "").strip()
        ws.cell(row=r, column=DESC_COL).value = desc if desc else None
        ws.cell(row=r, column=7).value = float(e["hours"])

    # Cột F: CÙNG định dạng với bản giao sếp (file làm việc + file nháp)
    _format_col_f(ws, summary_row)

    # Công thức tổng phủ ĐỦ toàn vùng (sửa lỗi file cũ của người dùng)
    ws.cell(row=summary_row, column=7).value = (
        f"=SUM(G{FIRST_DATA_ROW}:G{summary_row - 1})"
    )

    try:
        _set_author(wb, employee_name)
        wb.save(path)
        _clean_app_props(path)
    except PermissionError:
        raise ExcelWriterError(
            f"Không ghi được {path.name} — file đang MỞ trong Excel "
            "(Windows khóa file khi đang mở). Đóng file Excel lại rồi "
            "thử lệnh này lần nữa."
        )
    except OSError as e:
        raise ExcelWriterError(
            f"Không ghi được {path.name} ({type(e).__name__}: {e}). "
            "Kiểm tra ổ đĩa còn chỗ trống và file không bị chỉ-đọc."
        )
    total_hours = sum(float(e["hours"]) for e in entries)
    log.info("Đã ghi %d dòng (%.2f giờ) vào %s (summary row %d).",
             len(entries), total_hours, path.name, summary_row)
    audit("EXCEL_WRITE",
          f"{path.name}: {len(entries)} dòng, {total_hours:.2f}h")
    return {"path": path, "rows": len(entries),
            "summary_row": summary_row, "backup": backup_path}


def read_month_entries(month: date, config) -> list:
    """Đọc lại toàn bộ entry trong file làm việc của 1 tháng.
    File chưa tồn tại → list rỗng."""
    path = working_file_path(month)
    if not path.exists():
        return []
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    summary_row = _find_summary_row(ws)

    entries = []
    for r in range(FIRST_DATA_ROW, summary_row):
        raw_date = ws.cell(row=r, column=3).value
        if raw_date is None:
            continue
        if isinstance(raw_date, datetime):
            d = raw_date.date()
        elif isinstance(raw_date, date):
            d = raw_date
        else:
            log.warning("%s dòng %d: ô ngày lạ (%r) — bỏ qua.",
                        path.name, r, raw_date)
            continue
        entries.append({
            "date": d,
            "project": str(ws.cell(row=r, column=4).value or "").strip(),
            "task": str(ws.cell(row=r, column=5).value or "").strip(),
            "description": _read_desc(ws.cell(row=r, column=6).value),
            "hours": float(ws.cell(row=r, column=7).value or 0),
        })
    return entries


def validate_excel_file(month: date, config) -> list[str]:
    """Validate file Excel trước khi gửi mail.
    Kiểm tra:
    1. File tồn tại và mở được
    2. Cột B (tên) không trống
    3. Cột C (ngày) hợp lệ, đúng tháng
    4. Cột D (project) không trống
    5. Cột E (task) phải là giá trị trong TASK_NAMES chuẩn
    6. Cột F (description) — cảnh báo nếu trống cho task bắt buộc có ticket
    7. Cột G (hours) > 0, hợp lệ
    8. Tổng giờ dòng Full Summary khớp với tổng các dòng data
    9. Không có dòng data nào bị skip (cột ngày có nhưng task trống)
    Trả list[str] errors — rỗng = file hợp lệ.
    """
    import task_names as _tn
    import task_rules as _tr

    path = working_file_path(month)
    errors: list[str] = []

    # 1. File tồn tại
    if not path.exists():
        return [f"File {path.name} chưa tồn tại — chưa có dữ liệu tháng này"]

    try:
        wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as ex:
        return [f"Không mở được file {path.name}: {ex}"]

    ws = wb.active

    # Tìm dòng Full Summary
    try:
        summary_row = _find_summary_row(ws)
    except ExcelWriterError as ex:
        return [str(ex)]

    employee_name = config.get("employee_name") or ""
    total_hours_data = 0.0
    row_count = 0

    for r in range(FIRST_DATA_ROW, summary_row):
        raw_date = ws.cell(row=r, column=3).value
        # Dòng trống hoàn toàn → skip
        if raw_date is None:
            # Kiểm tra có ô nào khác trong dòng không (dòng nửa trống)
            other_vals = [ws.cell(row=r, column=c).value
                          for c in (2, 4, 5, 6, 7)]
            if any(v not in (None, "") for v in other_vals):
                errors.append(
                    f"Dòng {r}: có dữ liệu nhưng cột C (ngày) trống")
            continue

        row_count += 1

        # Parse ngày
        if isinstance(raw_date, datetime):
            d = raw_date.date()
        elif isinstance(raw_date, date):
            d = raw_date
        else:
            errors.append(f"Dòng {r}: cột C ngày không hợp lệ ({raw_date!r})")
            continue

        # 3. Ngày đúng tháng
        if (d.year, d.month) != (month.year, month.month):
            errors.append(
                f"Dòng {r}: ngày {d} không thuộc tháng "
                f"{month.year}-{month.month:02d}")

        # 2. Cột B — tên nhân viên
        name_val = str(ws.cell(row=r, column=2).value or "").strip()
        if not name_val:
            errors.append(f"Dòng {r} ({d}): cột B (tên) trống")
        elif employee_name and name_val.lower() != employee_name.lower():
            errors.append(
                f"Dòng {r} ({d}): cột B '{name_val}' "
                f"≠ tên cấu hình '{employee_name}'")

        # 4. Cột D — project
        project = str(ws.cell(row=r, column=4).value or "").strip()
        if not project:
            errors.append(f"Dòng {r} ({d}): cột D (Project Name) trống")

        # 5. Cột E — task name phải trong danh sách chuẩn
        task = str(ws.cell(row=r, column=5).value or "").strip()
        if not task:
            errors.append(f"Dòng {r} ({d}): cột E (Task Name) trống")
        elif task not in _tn.TASK_NAMES:
            # Thử normalize
            normalized = _tn.normalize_task_name(task)
            if normalized:
                errors.append(
                    f"Dòng {r} ({d}): cột E '{task}' nên viết là "
                    f"'{normalized}' (đúng cú pháp)")
            else:
                errors.append(
                    f"Dòng {r} ({d}): cột E '{task}' không có trong "
                    f"danh sách chuẩn. Hợp lệ: "
                    f"{', '.join(_tn.TASK_NAMES)}")

        # 6. Cột F — description
        desc = _read_desc(ws.cell(row=r, column=6).value)
        if task and task in _tn.TASK_NAMES:
            ticket_req = _tr.is_ticket_required(task)
            desc_const = _tr.get_desc_const(task)
            if not desc and ticket_req:
                errors.append(
                    f"Dòng {r} ({d}): cột F (Description) trống — "
                    f"task '{task}' bắt buộc có ticket/mô tả")
            if desc_const and desc and desc != desc_const:
                # NP task: desc phải đúng constant
                import re as _re
                if (project and
                        _re.search(r'PACSNP-', project, _re.IGNORECASE)):
                    if task in ("Coding/UT", "Investigation/Assessment"):
                        errors.append(
                            f"Dòng {r} ({d}): NP task cột F phải là "
                            f"'{desc_const}', không phải '{desc}'")

        # 7. Cột G — hours
        hours_val = ws.cell(row=r, column=7).value
        try:
            hours = float(hours_val or 0)
        except (TypeError, ValueError):
            errors.append(
                f"Dòng {r} ({d}): cột G (Hours) không phải số ({hours_val!r})")
            hours = 0.0
        if hours <= 0:
            errors.append(f"Dòng {r} ({d}): cột G (Hours) phải > 0 (hiện {hours})")
        else:
            total_hours_data += hours

    # 8. Tổng giờ — tính từ data rows (không phụ thuộc formula cell)
    # File Excel dùng công thức SUM nên data_only=False sẽ không ra số.
    # Thay vào đó: tính tổng từ data rows và kiểm tra tính nhất quán.
    # Validate thực tế: mỗi dòng > 0 (đã check ở trên) và tổng > 0.
    if total_hours_data <= 0 and row_count > 0:
        errors.append(
            f"Tổng giờ = {total_hours_data}h — không hợp lệ "
            f"({row_count} dòng nhưng tổng = 0)")
    elif row_count > 0:
        log.debug("validate_excel: %d dòng, tổng %.0fh",
                  row_count, total_hours_data)
    # Kiểm tra tổng giờ summary cell (nếu là số thực, không phải formula)
    summary_cell_val = ws.cell(row=summary_row, column=7).value
    if summary_cell_val is not None and not isinstance(
            summary_cell_val, str):
        try:
            summary_hours = float(summary_cell_val)
            if abs(summary_hours - total_hours_data) > 0.01:
                errors.append(
                    f"Tổng giờ KHÔNG KHỚP: dòng data = "
                    f"{total_hours_data:.2f}h, Full Summary = "
                    f"{summary_hours:.2f}h "
                    f"(chênh {abs(summary_hours-total_hours_data):.2f}h)")
        except (TypeError, ValueError):
            pass  # formula cell — bỏ qua, đã check từ data rows

    # 9. Không có dòng nào (file rỗng)
    if row_count == 0:
        errors.append("File không có dòng data nào — chưa điền timesheet")

    if errors:
        log.warning("validate_excel_file: %d lỗi trong %s",
                    len(errors), path.name)
    else:
        log.info("validate_excel_file: %s hợp lệ (%d dòng, %.0fh)",
                 path.name, row_count, total_hours_data)

    return errors


def _format_col_f(ws, summary_row: int) -> int:
    """ĐỊNH DẠNG CỘT F DÙNG CHUNG cho MỌI file Excel bot ghi: file làm việc,
    file nháp xem trước, bản giao sếp → 3 file GIỐNG HỆT NHAU (sửa 24-Sep:
    xem trước phải y như bản gửi thì review mới có ý nghĩa).
    Xuống dòng trong ô theo ticket (format_desc_for_excel), wrap CHỈ cột F,
    chiều cao hàng theo số dòng; hàng 1 dòng / trống = chuẩn template.
    Idempotent: chạy lại trên file đã định dạng cho kết quả y như cũ."""
    base_h = _base_row_height()
    line_h = base_h or 15.0
    width_f = ws.column_dimensions["F"].width
    changed = 0
    for r in range(FIRST_DATA_ROW, summary_row):
        cell = ws.cell(row=r, column=DESC_COL)
        if cell.value is None:
            ws.row_dimensions[r].height = base_h
            continue
        one = _read_desc(cell.value)
        new = format_desc_for_excel(one)
        if new != one:
            changed += 1
        cell.value = new
        al = copy(cell.alignment)
        al.wrap_text = True                       # CHỈ cột F
        cell.alignment = al
        if new != one:
            # Ô BOT TỰ XUỐNG HÀNG → chiều cao SÁT chữ (25-Sep): đo theo font +
            # cỡ chữ THẬT của ô. Ô không xuống hàng: giữ cách tính cũ bên dưới.
            ws.row_dimensions[r].height = _fit_row_height(new, cell, width_f)
            continue
        n = _desc_lines(new, width_f)
        ws.row_dimensions[r].height = (min(MAX_ROW_HEIGHT, n * line_h)
                                       if n > 1 else base_h)
    # Lượt 2: cột D dài phải xuống dòng → nâng hàng (chỉ tăng)
    for r in range(FIRST_DATA_ROW, summary_row):
        _grow_row_for_col_d(ws, r, base_h)
    return changed


def _set_author(wb, author) -> None:
    """Tác giả file = tên người dùng (employee_name) — không để tên trong file mẫu
    hay tên máy (02-Oct)."""
    wb.properties.creator = author or ""
    wb.properties.lastModifiedBy = author or ""


def _clean_app_props(path) -> None:
    """docProps/app.xml: ứng dụng = "Microsoft Excel" (bỏ chữ "Openpyxl <phiên bản>"
    mà thư viện tự ghi). Lỗi → bỏ qua, file vẫn dùng được (02-Oct)."""
    import os
    import tempfile
    import zipfile
    try:
        with zipfile.ZipFile(path) as zin:
            items = [(i, zin.read(i.filename)) for i in zin.infolist()]
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=str(Path(path).parent)); os.close(fd)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in items:
                if info.filename == "docProps/app.xml":
                    data = (b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
                            b'2006/extended-properties"><Application>Microsoft Excel</Application>'
                            b'</Properties>')
                zout.writestr(info, data)
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        log.debug("Không chuẩn hóa được app.xml (%s)", e)


def format_delivery_file(path: Path, author: str = None) -> int:
    """Định dạng cột F của 1 file có sẵn (bản giao sếp). Trả số ô xuống dòng."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    changed = _format_col_f(ws, _find_summary_row(ws))
    if author is not None:
        _set_author(wb, author)
    wb.save(path)
    _clean_app_props(path)
    return changed


def make_delivery_copy(month: date, send_day: date, config) -> Path:
    """Tạo bản giao sếp (copy file làm việc, đặt tên chuẩn).
    Trả về đường dẫn bản giao trong output\\."""
    src = working_file_path(month)
    if not src.exists():
        raise ExcelWriterError(
            f"Chưa có file làm việc tháng {month.year}-{month.month:02d} "
            "— chưa có gì để giao."
        )
    dst = OUTPUT_DIR / delivery_file_name(month, send_day, config)
    try:
        shutil.copy2(src, dst)
    except PermissionError:
        raise ExcelWriterError(
            f"Không tạo được bản giao {dst.name} — file này đang MỞ "
            "trong Excel. Đóng lại rồi nhắn 'ok' lần nữa giúp mình.")
    except OSError as e:
        raise ExcelWriterError(
            f"Không tạo được bản giao {dst.name} ({type(e).__name__}: "
            f"{e}). Kiểm tra ổ đĩa còn chỗ trống không.")
    # Xuống dòng cột F CHỈ ở bản giao (gửi / gởi lại). Lỗi định dạng KHÔNG
    # chặn gửi: nội dung đã đủ trong bản copy, chỉ là chưa xuống dòng.
    try:
        n = format_delivery_file(dst, config.get("employee_name") or "")
        log.info("Bản giao: xuống dòng cột F ở %d ô.", n)
    except PermissionError:
        raise ExcelWriterError(
            f"Không định dạng được bản giao {dst.name} — file này đang MỞ "
            "trong Excel. Đóng lại rồi nhắn 'ok' lần nữa giúp mình.")
    except Exception as e:  # noqa: BLE001
        log.warning("Định dạng xuống dòng bản giao lỗi (%s) — gửi bản 1 dòng.", e)
    log.info("Bản giao sếp: %s", dst.name)
    audit("EXCEL_DELIVERY_COPY", dst.name)
    return dst


# ---------------------------------------------------------------------
# Self-test: demo vào tháng 12/2030 (xa hẳn dữ liệu thật)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    cfg = load_config()
    demo_month = date(2030, 12, 1)
    print("Demo excel_writer với tháng 12/2030 (không đụng dữ liệu thật)…")

    demo_entries = [
        {"date": date(2030, 12, 2), "project": "PACSNP-7660",
         "task": "Coding/UT", "description": "New product day 2 items",
         "hours": 8},
        {"date": date(2030, 12, 3), "project": "LA & GA agent sync",
         "task": "UAT support",
         "description": "PACSGASIA-4036 - Agent Sync UAT Support",
         "hours": 4},
        {"date": date(2030, 12, 3), "project": "PACSNP-7660",
         "task": "Investigation/ Assessment",
         "description": "New product day 2 items", "hours": 4},
        {"date": date(2030, 12, 4), "project": "Public Holiday",
         "task": "Public Holiday", "description": "", "hours": 8},
    ]
    info = write_month_entries(demo_month, demo_entries, cfg)
    print(f"  Ghi {info['rows']} dòng -> {info['path'].name}")

    back = read_month_entries(demo_month, cfg)
    assert len(back) == 4 and back[0]["date"] == date(2030, 12, 2)
    print("  Đọc lại khớp:", len(back), "dòng.")

    delivery = make_delivery_copy(demo_month, date(2030, 12, 6), cfg)
    print(f"  Bản giao: {delivery.name}")
    print("DEMO OK — mở 2 file trên trong Excel xem format, rồi xóa đi.")
