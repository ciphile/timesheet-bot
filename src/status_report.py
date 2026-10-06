"""
status_report.py — Nội dung lệnh /status (thêm 24-Sep-2026).

Tách khỏi bot.py để test được không cần Telegram. bot.cmd_status chỉ gọi
build_status(config) rồi gửi.

Gồm 3 khối:
  🗓️ TIMESHEET : tình trạng hiện tại (7 trạng thái), kỳ đang mở, điền tới
                ngày nào, từng ngày T2–T6 có/thiếu dữ liệu, tin chờ, Excel
  🏖️ NGÀY PHÉP : Annual / Sick / Special (đã chốt + dự kiến), sắp hết hạn
  ⚙️ HỆ THỐNG  : mail đang dùng, AI, backup, cảnh báo dữ liệu hỏng
Mỗi khối bọc try riêng: 1 khối lỗi thì vẫn hiện các khối còn lại.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from log_setup import get_logger

log = get_logger("status_report")

_THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
_THU_FULL = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu",
             "thứ Bảy", "Chủ nhật"]

# Nhãn dễ hiểu cho các lời hỏi đang chờ (state["conversation"]["awaiting"])
_AWAIT_LABEL = {
    "past_edit_request": "nội dung cần sửa (/edittimesheet)",
    "past_edit_confirm": "xác nhận bản sửa timesheet ('ok' / sửa lại / 'hủy')",
    "compose_ai_request": "nội dung email cho sếp (/composemail)",
    "compose_manual_input": "nội dung email tự gõ (/composemanual)",
    "compose_confirm": "duyệt email nghỉ phép ('ok' để gửi)",
    "personal_mail_confirm": "xác nhận chuyển sang Gmail cá nhân",
    "update_leave_input": "số ngày phép cần nhập (/updateleave)",
    "update_leave_confirm": "xác nhận lưu số ngày phép",
    "clear_notes_confirm": "xác nhận /clearnotes (YES)",
    "reset_notes_confirm": "xác nhận /resetnotes (YES)",
}


def _d(d: date) -> str:
    return f"{_THU[d.weekday()]} {d:%d/%m}"


def _task_short(entries: list) -> str:
    parts = []
    for e in entries:
        h = float(e.get("hours") or 0)
        parts.append(f"{e.get('task', '?')} {h:g}h")
    s = ", ".join(parts)
    return s if len(s) <= 48 else s[:46] + "…"


# ---------------------------------------------------------------------
# Khối 1 — TIMESHEET
# ---------------------------------------------------------------------
def _timesheet_block(config, state: dict, today: date) -> list[str]:
    import daily_store
    import excel_writer
    import state as state_mod
    import validator

    lines = ["🗓️ TIMESHEET"]
    conv = state.get("conversation") or {}
    awaiting = conv.get("awaiting")
    draft = state.get("draft")
    last_sent = state_mod.last_sent_date(state)
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    sent_week = last_sent is not None and last_sent >= friday

    # ---- Tình trạng (ưu tiên từ trên xuống) ----
    if awaiting == "ts_mail_confirm":
        st = ("📧 ĐANG XEM TRƯỚC EMAIL timesheet — nhắn 'ok' để GỬI sếp, "
              "'hủy' / /resetmailts để thôi")
    elif awaiting == "resend_confirm":
        st = (f"📧 ĐANG XEM TRƯỚC GỞI LẠI (tháng "
              f"{', '.join(conv.get('months') or [])}) — 'ok' để gửi, 'hủy' để thôi")
    elif draft:
        ds = date.fromisoformat(draft["period_start"])
        de = date.fromisoformat(draft["period_end"])
        st = (f"📝 BẢN NHÁP ĐÃ TẠO (kỳ {_d(ds)} → {_d(de)}, tạo "
              f"{date.fromisoformat(draft.get('created_at', today.isoformat())):%d/%m}) "
              "— nhắn 'ok' để xem email trước khi gửi · /checkdraft xem lại")
    elif awaiting is True:
        n = len((state.get("last_questions") or {}).get("questions") or [])
        st = (f"❓ CHƯA TẠO ĐƯỢC NHÁP — còn {n or 'vài'} câu hỏi chờ bro trả lời "
              "(trả lời rồi bot soạn tiếp; /forcedraft nếu muốn bỏ qua)")
    elif sent_week:
        st = (f"✅ ĐÃ GỬI tuần này ({_d(last_sent)}). Tuần mới bắt đầu "
              f"{_d(monday + timedelta(days=7))}")
    else:
        st = (f"✍️ ĐANG NHẬP HẰNG NGÀY — {_THU_FULL[4]} {friday:%d/%m} 17:00 "
              "bot tự soạn nháp (hoặc /weeklyrun)")
    lines.append(f"Tình trạng: {st}")
    if state.get("hold"):
        lines.append("⏸️ KHOAN GỞI đang BẬT — bot KHÔNG tự gửi · nhắn 'bỏ khoan' để cho gửi")
    if awaiting and awaiting is not True and awaiting in _AWAIT_LABEL:
        lines.append(f"💬 Đang chờ bro: {_AWAIT_LABEL[awaiting]}")

    # ---- Kỳ đang mở + từng ngày ----
    pd = daily_store.load_all()
    if not sent_week:
        start, end = validator.period_bounds(friday, last_sent)
        try:
            import sg_holidays
            ph = {}
            for y in {start.year, end.year}:
                ph.update(sg_holidays.get_holidays(y, config=config,
                                                   allow_fetch=False) or {})
        except Exception as e:  # noqa: BLE001
            log.debug("status: không đọc được lịch lễ (%s)", e)
            ph = {}
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)
                if (start + timedelta(days=i)).weekday() < 5]
        sent_txt = f"gửi gần nhất: {_d(last_sent)}" if last_sent else "chưa từng gửi"
        if last_sent and monday <= last_sent < friday:
            sent_txt += " — đã gửi SỚM"
        lines.append(f"Kỳ đang mở: {_d(start)} → {_d(end)} ({sent_txt})")
        have = [d for d in days if d.isoformat() in pd]
        missing = [d for d in days if d <= today and d.isoformat() not in pd
                   and d.isoformat() not in ph]
        upto = max(have) if have else None
        lines.append(f"Đã điền tới: {_d(upto) if upto else '(chưa có ngày nào)'}"
                     f" · có dữ liệu {len(have)}/{len(days)} ngày làm việc")
        for d in days[-10:]:
            iso = d.isoformat()
            tag = " (hôm nay)" if d == today else ""
            if iso in pd:
                ents = pd[iso].get("entries", [])
                tot = sum(float(e.get("hours") or 0) for e in ents)
                warn = "" if abs(tot - (config.get("hours_per_day") or 8)) < 0.01 else " ⚠️"
                lines.append(f"  {_d(d)} ✓ {tot:g}h{warn}  {_task_short(ents)}{tag}")
            elif iso in ph:
                lines.append(f"  {_d(d)} 🎌 lễ {ph[iso]} (tự điền khi soạn nháp){tag}")
            elif d <= today:
                lines.append(f"  {_d(d)} ✗ CHƯA CÓ{tag}")
            else:
                lines.append(f"  {_d(d)} · chưa tới")
        if len(days) > 10:
            lines.append(f"  (… và {len(days) - 10} ngày trước đó)")
        if missing:
            lines.append("⚠️ Thiếu dữ liệu: " + ", ".join(_d(d) for d in missing))

    # ---- Việc còn treo ----
    edited = state.get("last_edited_months") or []
    if edited:
        lines.append(f"✏️ Đã sửa tháng {', '.join(edited)} nhưng CHƯA gởi lại "
                     "→ nhắn 'gởi lại'")
    q = state.get("pending_notes") or []
    if q:
        lines.append(f"📥 {len(q)} TIN CHỜ XỬ LÝ (AI lỗi lúc nhắn) — bot đang CHẶN "
                     "tạo nháp/gửi → /retrynotes (xem: /retrynotes xem)")
    # ---- Excel tháng này ----
    p = excel_writer.working_file_path(today.replace(day=1))
    if p.exists():
        mt = datetime.fromtimestamp(p.stat().st_mtime)
        lines.append(f"📁 Excel tháng {today:%m}: output\\{p.name} "
                     f"(cập nhật {mt:%d/%m %H:%M})")
    else:
        lines.append(f"📁 Excel tháng {today:%m}: chưa có (tạo khi soạn nháp/gửi)")
    return lines


# ---------------------------------------------------------------------
# Khối 2 — NGÀY PHÉP
# ---------------------------------------------------------------------
def _leave_block(config, state: dict, today: date) -> list[str]:
    import leave_balance as lb
    r = lb.compute_balance(config, state, today)
    lines = [f"🏖️ NGÀY PHÉP {r['year']} (reset 1/1)"]
    for kind, name in (("annual", "Annual Leave"), ("sick", "Sick Leave"),
                       ("special", "Special Leave")):
        x = r[kind]
        tot = f"/{lb._num(x['entitled'])}" if kind != "special" else ""
        s = f"• {name}: còn {lb._num(x['balance_confirmed'])}{tot}"
        if x["used_pending"] > 1e-9:
            s += (f" → sau khi gửi tuần này còn "
                  f"{lb._num(x['balance_projected'])}")
        if x.get("baseline"):
            s += f" (mốc nhập tay {x['baseline']['as_of']:%d/%m})"
        if x["balance_projected"] < -1e-9:
            s += " ⚠️ ÂM"
        lines.append(s)
    for c in r["special"]["credits"]:
        if c["expiry"] >= today and c["remaining"] > 1e-9:
            lines.append(f"   ◦ ngày bù lễ {c['name']} — dùng trước "
                         f"{c['expiry']:%d/%m} (còn {(c['expiry'] - today).days} ngày)")
    for c in r["special"]["expiring"]:
        lines.append(f"⏰ SẮP HẾT HẠN: ngày bù lễ {c['name']} ({c['expiry']:%d/%m})")
    for m in r.get("excel_errors", []):
        lines.append(f"⚠️ File Excel tháng {m} đọc lỗi — ngày nghỉ tháng đó chưa được tính")
    lines.append("Chi tiết: /leavebal · /leavelog · sửa số: /updateleave")
    return lines


# ---------------------------------------------------------------------
# Khối 3 — HỆ THỐNG
# ---------------------------------------------------------------------
def _system_block(config, state: dict, today: date) -> list[str]:
    import ai_client
    import notes_store
    from config_loader import CORRUPT_DIR, PARSED_SNAPSHOT_DIR
    lines = ["⚙️ HỆ THỐNG"]
    if state.get("mail_mode") == "personal" and getattr(config, "gmail_ok", True):
        lines.append("Gửi mail bằng: GMAIL CÁ NHÂN (Bcc mail công ty) · "
                     "/personalmailoff để về mail công ty")
    else:
        from config_loader import personal as _personal
        lines.append("Gửi mail bằng: MAIL CÔNG TY (Bcc "
                     f"{_personal('bcc_when_company', 'không')})")
    try:
        if ai_client.is_rule_parser_mode():
            lines.append("🔌 AI hôm nay đang LỖI → bot tự bóc bằng luật (rule)")
    except Exception:  # noqa: BLE001
        pass
    try:
        lines.append(ai_client.usage_summary(config))
    except Exception as e:  # noqa: BLE001
        lines.append(f"AI: (không đọc được thống kê: {e})")
    lines.append(f"Ghi chú nhắn hôm nay: {notes_store.count_notes_today()}")
    snaps = sorted(PARSED_SNAPSHOT_DIR.glob("parsed_days_*.json")) \
        if PARSED_SNAPSHOT_DIR.exists() else []
    if snaps:
        lines.append(f"💾 Backup parsed_days mới nhất: data\\backup\\"
                     f"parsed_days_daily\\{snaps[-1].name}")
    else:
        lines.append("💾 Backup parsed_days: chưa có (tự chụp khi bot khởi động)")
    bad = sorted(CORRUPT_DIR.glob("parsed_days.json.corrupt_*")) \
        if CORRUPT_DIR.exists() else []
    if bad:
        lines.append(f"⚠️ parsed_days.json từng bị HỎNG — bản hỏng: data\\backup\\"
                     f"corrupt\\{bad[-1].name}. Nếu thấy thiếu ngày: chép bản mới "
                     "nhất trong data\\backup\\parsed_days_daily\\ về "
                     "data\\parsed_days.json rồi khởi động lại bot.")
    return lines


def build_status(config, state: dict = None, now: datetime = None) -> str:
    import state as state_mod
    state = state if state is not None else state_mod.load_state()
    now = now or datetime.now()
    today = now.date()
    out = [f"📊 TRẠNG THÁI — {_THU_FULL[today.weekday()]} {today:%d/%m/%Y} "
           f"{now:%H:%M}", "━━━━━━━━━━━━━━━━━━"]
    for name, fn in (("timesheet", _timesheet_block), ("ngày phép", _leave_block),
                     ("hệ thống", _system_block)):
        try:
            out += fn(config, state, today)
        except Exception as e:  # noqa: BLE001 — 1 khối lỗi không làm mất cả /status
            log.exception("status: khối %s lỗi", name)
            out.append(f"({name}: lỗi đọc — {type(e).__name__}: {e})")
        out.append("━━━━━━━━━━━━━━━━━━")
    return "\n".join(out[:-1])
