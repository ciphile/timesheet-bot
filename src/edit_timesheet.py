"""
edit_timesheet.py — [KHÔNG CÒN DÙNG — GIỮ THAM CHIẾU]

⚠️ LỊCH SỬ (22-Sep-2026):
Module này TỪNG xử lý /edittimesheet (sửa timesheet đã gửi). Nhưng nó
có LỖ HỔNG: luôn GHI ĐÈ cả ngày, KHÔNG làm được "thêm task giữ task cũ".

ĐÃ THAY bằng note_action.py — module CRUD chung cho CẢ /edittimesheet
LẪN ghi chú thường:
  - 7 action rõ ràng (ADD_TASK/REPLACE_DAY/DELETE...) — phân biệt được
    "thêm task" vs "ghi đè ngày" (cái edit_timesheet cũ không làm được)
  - Validate chặt hơn (hours âm, trùng D/E/F, tự áp project_const...)
  - Cùng vòng lặp xác nhận + message cho cả 2 luồng

bot.py giờ KHÔNG gọi hàm nào của file này nữa (chỉ còn import thừa,
có thể bỏ). Giữ file để tham chiếu logic cũ nếu cần.

---
(Docstring gốc)
Module PHỤ sửa timesheet ĐÃ GỬI (an toàn, có xác nhận).

Vấn đề: sửa timesheet đã gửi bằng ngôn ngữ tự nhiên tự do dễ khiến AI
hiểu nhầm → sửa/xóa nhầm. Module này bắt người dùng đi qua 1 LỆNH riêng
(/edittimesheet) với vòng lặp xác nhận rõ ràng trước khi ghi Excel.

STANDALONE: chỉ GỌI LẠI:
  - ai_client.generate_json()   → parse ghi chú sửa thành entries
  - orchestrator.prepare_past_edit() → dựng preview bản sửa
  - orchestrator.apply_past_edit()   → ghi Excel + parsed_days

KHÔNG tự gửi mail. Sau khi sửa xong, người dùng tự /sendmail hoặc "gởi lại"
nếu muốn gửi lại cho sếp.

Luồng:
  /edittimesheet → bot hỏi "sửa ngày nào, task gì"
  → người dùng gõ: "ngày 10/5: nghỉ phép 2h, 6h sdf PACSGASIA-7763"
  → AI parse thành entries → prepare_past_edit dựng preview
  → bot hiện preview → người dùng "ok" → apply → ghi Excel + parsed_days
  → hoặc người dùng nói sửa lại → parse lại → vòng lặp

Cập nhật: 21-Sep-2026
"""

from __future__ import annotations

from datetime import date

import ai_client
import date_normalizer
from log_setup import get_logger

log = get_logger("edit_timesheet")


# ===========================================================================
# PROMPT — parse ghi chú sửa thành entries JSON
# ===========================================================================
_EDIT_PARSE_PROMPT = """Bạn là trợ lý bóc tách nội dung sửa timesheet của lập trình viên người dùng.

Đọc YÊU CẦU SỬA và trả về JSON các dòng task cho từng ngày.

QUY TẮC CỘT (giống timesheet):
- Mỗi task có: date (YYYY-MM-DD), project (cột D), task (cột E), description (cột F), hours.
- Task name (cột E) CHỈ dùng: Coding/UT, Investigation/Assessment, Issue Investigation, DFU, UAT Support, SDF, Annual Leave, Public Holiday, Special Leave.
- DFU / SDF / Issue Investigation → project = "Production Support".
- DFU → description = ticket PACSDFUM-xxxx.
- SDF → description = ticket/mô tả.
- Issue Investigation → description = ticket INC/mô tả.
- NP (project PACSNP-xxxx) + Coding/UT hoặc Investigation/Assessment → description = "New product day 2 items".
- UAT Support → project = tên project (PACSNP-xxxx), description = ticket.
- Annual Leave / Public Holiday / Special Leave → project = task name, description = "".
- Nghỉ phép nửa ngày / X tiếng → task = "Annual Leave", hours = số giờ nghỉ.
- Tổng giờ 1 ngày thường = 8h (trừ khi người dùng nói khác).

NĂM HIỆN TẠI: {year}. Nếu ghi chú chỉ có ngày/tháng (vd "10/5"), hiểu là năm {year}.

YÊU CẦU SỬA của người dùng:
"{request}"

Trả về JSON (không markdown, không giải thích):
{{"entries": [
  {{"date": "YYYY-MM-DD", "project": "...", "task": "...", "description": "...", "hours": 0}}
]}}
Nếu người dùng muốn XÓA ngày nào đó, thêm: "delete_days": ["YYYY-MM-DD"]."""


# ===========================================================================
# PARSE — ghi chú sửa → entries (gọi lại ai_client)
# ===========================================================================
_EDIT_MODIFY_PROMPT = """Bạn đang SỬA LẠI một bản sửa timesheet của người dùng.

BẢN SỬA HIỆN TẠI (các dòng task đã bóc tách):
{current}

YÊU CẦU SỬA LẠI của người dùng:
"{request}"

Áp dụng yêu cầu sửa lại lên BẢN HIỆN TẠI. GIỮ NGUYÊN ngày và các task
KHÔNG bị nhắc tới; chỉ đổi phần người dùng yêu cầu. TUYỆT ĐỐI giữ đúng NGÀY
của bản hiện tại (không đổi sang ngày khác trừ khi người dùng nói rõ).

QUY TẮC CỘT (giống timesheet):
- Task name (cột E) CHỈ dùng: Coding/UT, Investigation/Assessment, Issue Investigation, DFU, UAT Support, SDF, Annual Leave, Public Holiday, Special Leave.
- DFU/SDF/Issue Investigation → project = "Production Support".
- Tổng giờ 1 ngày thường = 8h.

Trả JSON (không markdown):
{{"entries": [
  {{"date": "YYYY-MM-DD", "project": "...", "task": "...", "description": "...", "hours": 0}}
]}}
Nếu xóa ngày: thêm "delete_days": ["YYYY-MM-DD"]."""


def modify_edit_request(current_parsed: dict, request: str, config) -> dict:
    """Sửa LẠI bản sửa hiện tại theo yêu cầu, GIỮ context (ngày + task cũ).
    current_parsed: {"entries": [...], "delete_days": [...]} — dạng dict
    với date là ISO string (từ state).
    Trả {"entries": [...], "delete_days": [...]} như parse_edit_request."""
    # Format bản hiện tại cho AI đọc
    lines = []
    for e in current_parsed.get("entries", []):
        d = e.get("date", "")
        desc = f" | {e.get('description','')}" if e.get("description") else ""
        lines.append(f"  {d}: {e.get('hours',0):g}h {e.get('task','')} "
                     f"— {e.get('project','')}{desc}")
    for d in current_parsed.get("delete_days", []):
        lines.append(f"  XÓA ngày {d}")
    current_text = "\n".join(lines) or "(trống)"

    prompt = _EDIT_MODIFY_PROMPT.format(
        current=current_text, request=request.strip())
    result = ai_client.generate_json(
        prompt, purpose="chat", config=config, session="edit_timesheet")

    # Parse kết quả (giống parse_edit_request)
    entries = []
    for e in result.get("entries", []):
        try:
            d = date.fromisoformat(str(e["date"]))
        except (ValueError, KeyError, TypeError):
            continue
        entries.append({
            "date": d,
            "project": str(e.get("project") or "").strip(),
            "task": str(e.get("task") or "").strip(),
            "description": str(e.get("description") or "").strip(),
            "hours": float(e.get("hours") or 0),
        })
    delete_days = []
    for ds in result.get("delete_days", []):
        try:
            delete_days.append(date.fromisoformat(str(ds)))
        except (ValueError, TypeError):
            pass
    if not entries and not delete_days:
        raise ai_client.AIError(
            "Không hiểu yêu cầu sửa lại — nói rõ hơn giúp mình.")
    return {"entries": entries, "delete_days": delete_days}


def parse_edit_request(request: str, config) -> dict:
    """Parse yêu cầu sửa thành entries. GỌI LẠI ai_client.generate_json.
    Trả {"entries": [...], "delete_days": [...]}.
    Raise ai_client.AIError nếu lỗi."""
    # Chuẩn hóa ngày TRƯỚC khi gửi AI: "10/9" → "10/09/2026 (thứ Năm)"
    # để AI không hiểu nhầm ngày (vd gán nhầm thành hôm nay).
    normalized = date_normalizer.normalize_dates_in_text(
        request.strip(), date.today())
    prompt = _EDIT_PARSE_PROMPT.format(
        year=date.today().year, request=normalized)
    result = ai_client.generate_json(
        prompt, purpose="chat", config=config, session="edit_timesheet")

    raw_entries = result.get("entries", [])
    if not raw_entries and not result.get("delete_days"):
        raise ai_client.AIError(
            "Không bóc tách được nội dung sửa — nói rõ ngày và task giúp mình.")

    # Convert date string → date object, validate cơ bản
    entries = []
    for e in raw_entries:
        try:
            d = date.fromisoformat(str(e["date"]))
        except (ValueError, KeyError, TypeError):
            continue
        entries.append({
            "date": d,
            "project": str(e.get("project") or "").strip(),
            "task": str(e.get("task") or "").strip(),
            "description": str(e.get("description") or "").strip(),
            "hours": float(e.get("hours") or 0),
        })

    delete_days = []
    for ds in result.get("delete_days", []):
        try:
            delete_days.append(date.fromisoformat(str(ds)))
        except (ValueError, TypeError):
            pass

    if not entries and not delete_days:
        raise ai_client.AIError(
            "Không bóc tách được ngày hợp lệ — nói rõ ngày (vd 10/05) giúp mình.")

    return {"entries": entries, "delete_days": delete_days}


# ===========================================================================
# FORMAT — hiện bản sửa để người dùng xác nhận
# ===========================================================================
def format_edit_preview(parsed: dict) -> str:
    """Hiện nội dung sửa đã bóc tách để người dùng xác nhận trước khi ghi."""
    thu = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm",
           "thứ Sáu", "thứ Bảy", "CN"]
    lines = ["✏️ NỘI DUNG SỬA (bóc tách từ yêu cầu):",
             "━━━━━━━━━━━━━━━━━━"]

    # Gom theo ngày
    by_day: dict = {}
    for e in parsed["entries"]:
        by_day.setdefault(e["date"], []).append(e)

    for d in sorted(by_day):
        t = thu[d.weekday()] if hasattr(d, "weekday") else ""
        lines.append(f"{t} {d.strftime('%d/%m/%Y')}:")
        total = 0.0
        for e in by_day[d]:
            total += e["hours"]
            desc = f" | {e['description']}" if e["description"] else ""
            lines.append(
                f"  • {e['hours']:g}h {e['task']} — {e['project']}{desc}")
        lines.append(f"  (tổng {total:g}h)")

    for d in parsed.get("delete_days", []):
        t = thu[d.weekday()] if hasattr(d, "weekday") else ""
        lines.append(f"🗑️ XÓA ngày {t} {d.strftime('%d/%m/%Y')}")

    lines += [
        "━━━━━━━━━━━━━━━━━━",
        "Đây là sửa vào timesheet ĐÃ GỬI cho sếp.",
        "Nhắn 'ok' để GHI vào Excel, hoặc nói mình sửa lại "
        "(vd 'đổi giờ thành 4h', 'ngày 11/5 nữa').",
        "Nhắn 'hủy' để bỏ.",
        "",
        "(Sau khi ghi xong, muốn gửi lại sếp thì dùng /sendmail "
        "hoặc nhắn 'gởi lại'.)",
    ]
    return "\n".join(lines)


# ===========================================================================
# SELF-TEST (không gọi AI thật)
# ===========================================================================
if __name__ == "__main__":
    print("=" * 55)
    print("EDIT_TIMESHEET SELF-TEST (không gọi AI thật)")
    print("=" * 55)

    # Test format_edit_preview
    parsed = {
        "entries": [
            {"date": date(2026, 5, 10), "project": "Annual Leave",
             "task": "Annual Leave", "description": "", "hours": 2.0},
            {"date": date(2026, 5, 10), "project": "Production Support",
             "task": "SDF", "description": "PACSGASIA-7763", "hours": 6.0},
        ],
        "delete_days": [],
    }
    preview = format_edit_preview(parsed)
    print(preview)
    assert "10/05/2026" in preview
    assert "SDF" in preview
    assert "tổng 8h" in preview
    print("\n✓ format_edit_preview OK (gom ngày, tính tổng giờ)")

    # Test có delete_days
    parsed2 = {"entries": [], "delete_days": [date(2026, 5, 11)]}
    prev2 = format_edit_preview(parsed2)
    assert "XÓA ngày" in prev2
    print("✓ format với delete_days OK")

    print("\n>>> ALL GREEN <<<")
