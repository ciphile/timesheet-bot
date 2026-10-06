"""
validator.py — Bộ luật kiểm tra + các phép biến đổi tất định.

Nguyên tắc: mọi thứ tính được bằng luật thì code làm, KHÔNG giao AI:
- Tính khoảng ngày cần báo cáo (mốc = sau lần gửi cuối, sàn = đầu tháng)
- Danh sách working day Mon–Fri (thứ/ngày lấy từ datetime, không tin tay)
- Viết hoa mã ticket (pacsnp-7660 -> PACSNP-7660)
- Khớp task name về đúng list chuẩn trong settings
- Chia giờ trong ngày: chia đều 8h phần chưa ghi, làm tròn 2 số lẻ,
  DÒNG CUỐI gánh phần dư cho tổng đúng 8.00
- Checklist trước khi gửi (PROJECT.md mục 9): thiếu ngày, lệch giờ,
  task lạ, UAT/DFU thiếu Jira, quá giờ…
"""

import re
from datetime import date, timedelta

from log_setup import get_logger

log = get_logger("validator")

# Mã ticket kiểu PACSNP-7660, PACSGASIA-4036, hoặc key ngắn kiểu Jira
# thật (GA-123, IT-4501)… Tiền tố tối thiểu 2 ký tự (chữ Jira key
# ngắn nhất thực tế); số tối thiểu 2 chữ số — CỐ Ý không cho phép số
# 1 chữ số, để không nhận nhầm cụm tiếng Việt/Anh thường gặp kiểu
# "no-1", "step-2", "phần-3" thành mã ticket giả (false positive
# nguy hiểm hơn: bot sẽ tưởng ĐàCÓ Jira ticket trong khi chỉ là văn
# xuôi, bỏ qua việc bắt buộc hỏi xin ticket thật).
TICKET_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,11}-\d{2,6})\b")


# ------------------------- khoảng thời gian --------------------------

def period_bounds(send_day: date, last_sent) -> tuple:
    """(start, end) của kỳ cần bảo đảm đầy đủ dữ liệu.
    start = sau ngày gửi cuối; chưa từng gửi -> đầu tháng của send_day.
    (Quét từ lần gửi cuối để tuần vắt tháng không lọt lưới.)"""
    if last_sent is None:
        start = send_day.replace(day=1)
    else:
        start = last_sent + timedelta(days=1)
    if start > send_day:
        start = send_day
    return start, send_day


def workdays_between(start: date, end: date) -> list:
    """Mọi ngày Mon–Fri trong [start, end] — nguồn sự thật về thứ/ngày."""
    days, d = [], start
    while d <= end:
        if d.weekday() <= 4:
            days.append(d)
        d += timedelta(days=1)
    return days


# --------------------------- chuẩn hóa -------------------------------

def uppercase_tickets(text: str) -> str:
    """Chỉ viết hoa các token dạng mã ticket, không đụng phần còn lại."""
    return TICKET_RE.sub(lambda m: m.group(1).upper(), text or "")


def normalize_task_name(raw: str, config=None):
    """Khớp task name về đúng list chuẩn trong task_names.py.
    config vẫn nhận được để backward-compatible nhưng không dùng nữa —
    nguồn sự thật là TASK_NAMES trong task_names.py."""
    import task_names as _tn
    key = " ".join((raw or "").lower().split())
    for name in _tn.TASK_NAMES:
        if " ".join(name.lower().split()) == key:
            return name
    # Thử alias mapping
    alias_result = _tn.normalize_task_name(raw)
    return alias_result


def needs_jira(task_name: str, config=None) -> bool:
    """Task cần có Jira/ticket trong description (theo task_rules.py)."""
    import task_rules as _tr
    return _tr.is_ticket_required(task_name)


def split_hours(tasks: list, hours_per_day: int) -> tuple:
    """Điền giờ cho các task 1 ngày. tasks: list dict, 'hours' có thể
    None. Trả (tasks_mới, lỗi|None). Luật PROJECT.md mục 4:
    - Task đã ghi giờ: giữ nguyên.
    - Phần còn lại chia đều cho task chưa ghi, 2 số lẻ, dòng CUỐI
      trong nhóm chưa-ghi gánh phần dư cho tổng đúng hours_per_day."""
    fixed = sum(float(t["hours"]) for t in tasks if t.get("hours") is not None)
    free = [t for t in tasks if t.get("hours") is None]
    if not free:
        # Không còn gì để chia — trả nguyên (chuẩn hóa float). Tổng
        # đúng/sai 8h là việc của find_issues (hour_mismatch): giữ
        # dữ liệu lại để bot HỎI, không đánh rớt (vd nửa ngày AL 4h
        # chờ người dùng khai nốt 4h còn lại).
        return [dict(t, hours=float(t["hours"])) for t in tasks], None
    remaining = hours_per_day - fixed
    if remaining <= 0:
        return tasks, (f"có task chưa ghi giờ nhưng giờ đã ghi đã đủ/"
                       f"vượt {hours_per_day}h — không biết chia sao")
    even = round(remaining / len(free), 2)
    result = []
    used = 0.0
    free_seen = 0
    for t in tasks:
        t = dict(t)
        if t.get("hours") is None:
            free_seen += 1
            if free_seen == len(free):
                t["hours"] = round(remaining - used, 2)   # dòng cuối gánh dư
            else:
                t["hours"] = even
                used = round(used + even, 2)
        else:
            t["hours"] = float(t["hours"])
        result.append(t)
    return result, None


# --------------------------- checklist -------------------------------

def validate_task_rules(entries: list, is_friday: bool = False) -> list:
    """Validate D/E/F combination theo task_rules.py.
    is_friday=True → cột F trống = ERROR không cho gửi.
    is_friday=False → cột F trống = WARNING hỏi lại.
    Trả list[str] mô tả lỗi.
    """
    import task_rules as _tr
    issues = []
    for e in entries:
        errs = _tr.validate_entry(
            project=str(e.get("project") or ""),
            task_name=str(e.get("task") or ""),
            description=str(e.get("description") or ""),
            hours=float(e.get("hours") or 0),
            is_friday=is_friday,
        )
        day = e.get("date")
        day_str = day.strftime("%d/%m/%Y") if hasattr(day, "strftime") else str(day)
        thu = ["thứ Hai","thứ Ba","thứ Tư","thứ Năm","thứ Sáu","thứ Bảy","CN"]
        thu_str = thu[day.weekday()] if hasattr(day, "weekday") else ""
        for err in errs:
            issues.append(f"Ngày {day_str} ({thu_str}): {err}")
    return issues


def validate_parsed_structure(parsed_days: dict, hours_per_day: int = 8) -> list[str]:
    """Kiểm tra CẤU TRÚC file parsed_days — bắt lỗi parse sai.
    Gọi ở các checkpoint quan trọng: sau khi ghi note_action, trước khi
    tạo bản nháp Excel, trước khi gửi mail.

    Bắt các lỗi:
    1. KEY ngày ≠ date trong entries (vd key "2026-09-25" nhưng entry
       ghi date "2026-09-22") → parse lệch, nguy hiểm
    2. Tổng giờ 1 ngày ≠ hours_per_day (thường 8h) — quá hoặc thiếu
    3. Ngày có entry trùng HỆT nhau (D/E/F giống → insert 2 lần)
    4. hours âm/0/phi lý trong 1 entry
    5. entry thiếu field bắt buộc (date/task/hours)

    Trả list[str] lỗi (rỗng = sạch). Mỗi lỗi ghi rõ ngày + vấn đề.
    """
    errors = []

    # 0. KEY NGÀY TRÙNG trong file JSON (json.load đã nuốt bản đầu,
    #    chỉ giữ bản cuối → mất dữ liệu). daily_store ghi lại ngày trùng
    #    ở lần đọc gần nhất.
    try:
        import daily_store
        dup_days = daily_store.last_load_duplicate_days()
        for d in dup_days:
            errors.append(
                f"Ngày {d}: bị GHI 2 LẦN trong parsed_days.json (key "
                f"trùng) — mỗi ngày chỉ được 1 lần. File đã mất bản đầu, "
                f"chỉ giữ bản cuối. Kiểm tra & sửa file.")
    except Exception:  # noqa: BLE001
        pass

    for key_iso, day_data in sorted(parsed_days.items()):
        entries = day_data.get("entries", [])
        if not entries:
            errors.append(f"Ngày {key_iso}: không có entry nào (rỗng).")
            continue

        # 1. KEY ≠ date trong entries
        for i, e in enumerate(entries):
            edate = str(e.get("date", "")).strip()
            if edate and edate != key_iso:
                errors.append(
                    f"Ngày {key_iso}: entry #{i+1} ghi date='{edate}' "
                    f"KHÁC key '{key_iso}' — parse LỆCH ngày, phải sửa.")

        # 2. Tổng giờ ≠ hours_per_day
        total = sum(float(e.get("hours") or 0) for e in entries)
        if abs(total - hours_per_day) > 0.01:
            errors.append(
                f"Ngày {key_iso}: tổng {total:g}h (phải đúng {hours_per_day}h) "
                f"— {len(entries)} task.")

        # 3. Entry trùng hệt (D/E/F giống)
        seen = {}
        for i, e in enumerate(entries):
            sig = (str(e.get("project","")).strip().lower(),
                   str(e.get("task","")).strip().lower(),
                   str(e.get("description","")).strip().lower())
            if sig in seen:
                errors.append(
                    f"Ngày {key_iso}: task trùng HỆT (D/E/F giống) — "
                    f"'{e.get('task','')}' xuất hiện 2 lần (entry "
                    f"#{seen[sig]+1} và #{i+1}).")
            else:
                seen[sig] = i

        # 4. hours phi lý
        for i, e in enumerate(entries):
            h = e.get("hours")
            if h is None or float(h) <= 0 or float(h) > 24:
                errors.append(
                    f"Ngày {key_iso}: entry #{i+1} '{e.get('task','')}' "
                    f"có giờ không hợp lệ ({h}).")

        # 5. Thiếu field bắt buộc
        for i, e in enumerate(entries):
            if not str(e.get("task","")).strip():
                errors.append(
                    f"Ngày {key_iso}: entry #{i+1} thiếu task (cột E).")

    return errors


def find_issues(entries: list, expected_days: list, ph_map: dict,
                config) -> dict:
    """Chạy checklist trên list entry của MỘT kỳ. Trả dict các vấn đề;
    dict rỗng = ĐẠT, được phép gửi.
    - missing_days   : working day không có dòng nào
    - hour_mismatch  : {iso: tổng giờ} ngày KHÁC 8h (nhỏ hơn HAY lớn
                       hơn đều bị bắt — rule người dùng 15-Sep)
    - week_mismatch  : {nhãn tuần: {expected, actual}} tổng TUẦN lệch
                       8h × số working day của tuần đó trong kỳ
                       (tuần đủ Mon–Fri = đúng 40h). Lớp phòng thủ
                       thứ 2, độc lập với check ngày.
    - unknown_task   : entry có task ngoài list chuẩn
    - missing_jira   : entry UAT/DFU mà description trống/không có ticket
    LƯU Ý: entries truyền vào phải GỒM CẢ các dòng Public Holiday đã
    autofill, vì check tuần đếm cả ngày lễ (lễ = 8h).
    """
    hours_per_day = config.get("hours_per_day")
    by_day = {}
    for e in entries:
        by_day.setdefault(e["date"], []).append(e)

    issues = {"missing_days": [], "hour_mismatch": {},
              "week_mismatch": {}, "unknown_task": [], "missing_jira": []}

    for d in expected_days:
        rows = by_day.get(d, [])
        if not rows:
            issues["missing_days"].append(d)
            continue
        total = round(sum(float(r["hours"]) for r in rows), 2)
        if abs(total - hours_per_day) > 1e-9:
            issues["hour_mismatch"][d.isoformat()] = total

    # ---- Check cấp TUẦN (độc lập với check ngày) ----
    # Mọi working day của kỳ (kể cả ngày lễ) gom theo tuần ISO;
    # tuần nào tổng giờ thực tế != 8h x số ngày -> báo.
    all_days = sorted(set(expected_days) | set(ph_map.keys()))
    weeks = {}
    for d in all_days:
        weeks.setdefault(d.isocalendar()[:2], []).append(d)
    for _, days in sorted(weeks.items()):
        expected_hours = hours_per_day * len(days)
        actual = round(sum(
            float(r["hours"])
            for d in days for r in by_day.get(d, [])), 2)
        if abs(actual - expected_hours) > 1e-9:
            label = f"{days[0].strftime('%d/%m')}–{days[-1].strftime('%d/%m')}"
            issues["week_mismatch"][label] = {
                "expected": expected_hours, "actual": actual}

    import task_rules as _tr
    for e in entries:
        if normalize_task_name(e["task"], config) is None:
            issues["unknown_task"].append(e)
        if needs_jira(e["task"], config):
            desc = e.get("description") or ""
            project = e.get("project") or ""
            # NP task với desc = constant "New product day 2 items"
            # KHÔNG cần ticket (NP Coding/UT + Investigation/Assessment)
            np_desc_const = _tr.get_desc_const(e["task"])
            is_np_with_const = (
                np_desc_const and desc == np_desc_const
                and project.upper().startswith("PACSNP"))
            # Có ticket = mã kiểu Jira (PACSDFUM-8793) HOẶC mọi dạng ticket mà
            # task_rules nhận khi ghi chú: INC/CHG/REQ (có/không gạch), Ticket#123,
            # "Ticket # 123". (Sửa 02-Oct: trước CHỈ nhận dạng CHỮ-SỐ → báo nhầm
            # "thiếu số Jira ticket" cho mọi Issue Investigation ghi Ticket#/INC.)
            has_ticket = bool(TICKET_RE.search(desc) or _tr.ALL_TICKET_RE.search(desc))
            # Task có tiền tố ticket + mô tả không trống → task_rules (validate_
            # task_rules bên dưới) ĐÃ kiểm & báo → không báo LẦN 2 (trùng dòng).
            covered = bool(_tr.get_ticket_prefix(e["task"]) and desc)
            if not has_ticket and not is_np_with_const and not covered:
                issues["missing_jira"].append(e)

    # Validate task rules (D/E/F combination) — 19-Sep-2026
    task_rule_errors = validate_task_rules(entries)
    if task_rule_errors:
        issues["task_rule_errors"] = task_rule_errors

    return {k: v for k, v in issues.items() if v}


def issue_lines(issues: dict) -> list[str]:
    """MỖI vấn đề = 1 phần tử (để đếm đúng "Còn N vấn đề"; bỏ dấu "- " đầu
    dòng vì nơi hiển thị tự thêm "• "). (Thêm 02-Oct.)"""
    return [l[2:] if l.startswith("- ") else l
            for l in describe_issues(issues).split("\n") if l.strip()]


def describe_issues(issues: dict) -> str:
    """Diễn dịch issues thành tiếng Việt để bot nhắn người dùng."""
    lines = []
    for d in issues.get("missing_days", []):
        thu = ["thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6"][d.weekday()]
        lines.append(f"- {thu} ngày {d.strftime('%d/%m')}: chưa có task nào")
    for iso, total in issues.get("hour_mismatch", {}).items():
        lines.append(f"- ngày {iso}: tổng {total:g}h (phải ĐÚNG 8h, "
                     "không hơn không kém)")
    for label, info in issues.get("week_mismatch", {}).items():
        lines.append(f"- tuần {label}: tổng {info['actual']:g}h "
                     f"(phải đúng {info['expected']:g}h)")
    for e in issues.get("unknown_task", []):
        lines.append(f"- ngày {e['date']}: task lạ {e['task']!r} "
                     "(không có trong danh sách chuẩn)")
    for e in issues.get("missing_jira", []):
        lines.append(f"- ngày {e['date']}: {e['task']} thiếu số ticket "
                     "trong description (vd Ticket# 123456, INC123456, PACSDFUM-1234)")
    for err in issues.get("task_rule_errors", []):
        lines.append(f"- {err}")
    return "\n".join(lines)
