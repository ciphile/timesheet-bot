"""
compose_email.py — Module PHỤ soạn & gửi email cho sếp.

STANDALONE: chỉ GỌI LẠI 2 module có sẵn của dự án timesheet:
  - ai_client.generate_json()  → dùng chung cách chọn model Gemini,
    cache, priority, fallback... y hệt timesheet. KHÔNG viết lại.
  - mailer.send_email()        → dùng chung cách gửi SMTP.

KHÔNG đụng bất kỳ module nào khác của timesheet → không gây bug,
không cần regression test lại phần gửi timesheet.

2 chế độ:
  1. AI mode (/composemail): người dùng nhắn tiếng Việt tóm tắt → AI soạn
     subject + body theo rule (súc tích, chuyên nghiệp, cảm ơn sếp,
     Regards + người dùng, gọi sếp sếp).
  2. Manual mode (/composemanual): người dùng tự nhập subject + body,
     KHÔNG gọi AI.

Cả 2 chế độ: bot hiện lại email (địa chỉ + subject + body) → người dùng
"ok" mới gửi. Sửa được nhiều lần trước khi gửi.

Cập nhật: 21-Sep-2026
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import ai_client
from log_setup import get_logger

log = get_logger("compose_email")


# ===========================================================================
# PROMPT — hướng dẫn AI soạn email xin nghỉ / đổi phép
# ===========================================================================
_COMPOSE_PROMPT = """Bạn là trợ lý soạn email công việc cho một lập trình viên tên {me} gửi cho sếp tên {boss}.

Đọc YÊU CẦU tiếng Việt của {me} và soạn 1 email tiếng Anh.

QUY TẮC BẮT BUỘC:
- Súc tích, ngắn gọn, chuyên nghiệp.
- Từ ngữ ĐƠN GIẢN, phổ thông, nhiều người dùng — KHÔNG dùng từ quá trịnh trọng/cao siêu.
- Viết đơn giản nhưng ĐẦY ĐỦ Ý.
- LUÔN mở đầu bằng "Hi {boss}" (gọi sếp là {boss}).
- LUÔN cảm ơn sếp (Thanks).
- LUÔN kết thúc bằng:
  Regards
  {me}
- Nếu là xin nghỉ phép: nêu rõ (các) ngày nghỉ.
{date_rules}
- Nếu nghỉ NỬA NGÀY: ghi rõ "halfday morning" (sáng) hoặc "halfday afternoon" (chiều) NGAY CẠNH ngày.
- Nếu {me} nói "as communicated" / "đã trao đổi" / "đã báo": mở đầu nội dung bằng "As communicated, ...".
- Nếu đổi ngày phép: ghi rõ "change my leave from <ngày cũ> to <ngày mới>".
- Subject ngắn gọn, mô tả đúng nội dung (vd "Leave Request - Thursday 10/9 & Friday 18/9").

VÍ DỤ 1 — xin nghỉ 2 ngày:
  Subject: Leave Request - Thursday 10/9 & Friday 18/9
  Body:
  Hi {boss}

  I'd like to take leave on Thursday 10/9 and Friday 18/9.
  Please help to approve
  Thanks

  Regards
  {me}

VÍ DỤ 2 — nghỉ nửa ngày:
  Subject: Leave Request - Monday 16/2 to Thursday 19/2
  Body:
  Hi {boss}

  I'd like to request leave the following days
  Monday 16/2 (halfday morning)
  Tuesday 17/2 (halfday afternoon)
  Thursday 19/2
  Please help to approve
  Thanks

  Regards
  {me}

VÍ DỤ 3 — đổi ngày phép (as communicated):
  Subject: Change of Leave Date
  Body:
  Hi {boss}

  As communicated, I will change my leave from Thursday 24/9 to Thursday 1/10
  Thanks

  Regards
  {me}

YÊU CẦU CỦA NGƯỜI DÙNG:
"{request}"

Trả về JSON đúng dạng (không markdown, không giải thích):
{{"subject": "...", "body": "Hi {boss}\\n\\n...\\n\\nRegards\\n{me}"}}
Trong body dùng \\n cho xuống dòng. Giữ đúng dòng trống giữa các đoạn như ví dụ."""


_MODIFY_PROMPT = """Bạn đang SỬA một email nháp cho {me} gửi sếp {boss}.

EMAIL HIỆN TẠI:
Subject: {subject}
Body:
{body}

YÊU CẦU SỬA của {me}:
"{request}"

Sửa email theo yêu cầu, GIỮ NGUYÊN các quy tắc:
- Hi {boss} mở đầu, Thanks, kết Regards + {me}.
- Súc tích, đơn giản, chuyên nghiệp.
- Nghỉ nửa ngày ghi "halfday morning/afternoon".
{date_rules}

Trả về JSON (không markdown):
{{"subject": "...", "body": "Hi {boss}\\n\\n...\\n\\nRegards\\n{me}"}}"""


# ===========================================================================
# AI MODE — soạn email từ yêu cầu tiếng Việt
# ===========================================================================
def compose_with_ai(request: str, config) -> dict:
    """Soạn email từ yêu cầu tiếng Việt của người dùng.

    GỌI LẠI ai_client.generate_json (dùng chung model/cache/priority
    của timesheet). Trả {"subject": str, "body": str}.
    Raise ai_client.AIError nếu AI lỗi (caller xử lý).
    """
    _today = date.today()
    _tomorrow = _today + timedelta(days=1)
    prompt = _COMPOSE_PROMPT.format(boss=_boss(), me=_me(), 
        request=request.strip(),
        date_rules=_build_date_rules(_today))
    result = ai_client.generate_json(
        prompt, purpose="chat", config=config, session="compose_email")
    return _validate_email_dict(result)


_EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]
_VN_DAYS = ["thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "thứ 7", "CN"]


def fmt_leave_day(d: date) -> str:
    """Định dạng ngày trong email nghỉ phép: 'Friday 25/9', 'Monday 5/10'.
    Ngày & tháng KHÔNG thêm số 0 (25/9, 5/10, 12/10)."""
    return f"{_EN_DAYS[d.weekday()]} {d.day}/{d.month}"


def _build_date_rules(today: date = None) -> str:
    """Rule ngày + BẢNG LỊCH tính sẵn bằng Python. AI (bản lite) hay
    tính SAI thứ của 1 ngày → không cho nó tự tính, chỉ cho tra bảng."""
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    rows = []
    for i in range(-7, 29):          # 1 tuần trước → 4 tuần tới
        d = today + timedelta(days=i)
        tag = " ← HÔM NAY" if i == 0 else (" ← NGÀY MAI" if i == 1 else "")
        rows.append(f"  {_VN_DAYS[d.weekday()]} {d.strftime('%d/%m/%Y')} "
                    f"= {fmt_leave_day(d)}{tag}")
    return (
        "- ⚠️ MỌI ngày nghỉ PHẢI có THỨ (tiếng Anh) + NGÀY dạng ngày/tháng "
        "KHÔNG số 0 đầu, lấy ĐÚNG từ BẢNG LỊCH bên dưới, KHÔNG tự tính thứ.\n"
        "  Đúng: 'Friday 25/9', 'Monday 5/10', 'Tuesday 13/10'.\n"
        "  Sai : '25/09', 'tomorrow' (thiếu ngày), '25/9' (thiếu thứ).\n"
        "  Được giữ chữ today/tomorrow/this afternoon NHƯNG phải kèm thứ+ngày:\n"
        f"  - 'nghỉ ngày mai' → 'tomorrow, {fmt_leave_day(tomorrow)}'\n"
        f"  - 'nghỉ chiều nay' → 'this afternoon, {fmt_leave_day(today)} "
        "(halfday afternoon)'\n"
        "  - Subject cũng dùng dạng này (vd 'Leave Request - "
        f"{fmt_leave_day(tomorrow)}').\n"
        "BẢNG LỊCH (tra ở đây):\n" + "\n".join(rows))


def modify_with_ai(current: dict, request: str, config) -> dict:
    """Sửa email nháp theo yêu cầu. GỌI LẠI ai_client.generate_json.
    Trả {"subject": str, "body": str}."""
    prompt = _MODIFY_PROMPT.format(boss=_boss(), me=_me(), 
        subject=current.get("subject", ""),
        body=current.get("body", ""),
        request=request.strip(),
        date_rules=_build_date_rules())
    result = ai_client.generate_json(
        prompt, purpose="chat", config=config, session="compose_email")
    return _validate_email_dict(result)


def _boss() -> str:
    from config_loader import personal
    return personal("boss_name", "Boss")


def _me() -> str:
    from config_loader import personal
    return personal("signature_name", "Me")


def _validate_email_dict(d: dict) -> dict:
    """Đảm bảo AI trả đúng {subject, body} và body có đủ Hi sếp/Regards/người dùng."""
    subject = (d.get("subject") or "").strip()
    body = (d.get("body") or "").strip()
    if not subject or not body:
        raise ai_client.AIError(
            "AI trả email thiếu subject hoặc body — thử lại nhé bro.")

    # Đảm bảo mở đầu Hi <tên sếp>
    if not body.lower().startswith(f"hi {_boss().lower()}"):
        body = f"Hi {_boss()}\n\n" + body

    # Đảm bảo kết Regards + người dùng
    low = body.lower()
    if "regards" not in low:
        body = body.rstrip() + f"\n\nRegards\n{_me()}"
    elif not low.rstrip().endswith(_me().lower()):
        # có Regards nhưng thiếu chữ ký
        body = body.rstrip() + f"\n{_me()}"

    return {"subject": subject, "body": body}


# ===========================================================================
# MANUAL MODE — người dùng tự nhập subject + body
# ===========================================================================
def compose_manual(subject: str, body: str) -> dict:
    """Chế độ nhập tay — KHÔNG gọi AI. Chỉ đóng gói lại.
    subject + body do người dùng tự soạn."""
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise ValueError("Thiếu subject.")
    if not body:
        raise ValueError("Thiếu nội dung email.")
    return {"subject": subject, "body": body}


def parse_manual_input(text: str) -> dict:
    """Tách subject và body từ input nhập tay của người dùng.

    Chấp nhận 2 dạng:
    A) "Subject: ...\\n<body>"  — dòng đầu bắt đầu bằng "Subject:"
    B) "<dòng đầu là subject>\\n<phần còn lại là body>"

    Trả {"subject", "body"}. Thiếu → raise ValueError.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Chưa nhập gì cả.")

    lines = text.split("\n")
    first = lines[0].strip()

    # Dạng A: "Subject: xxx"
    if first.lower().startswith("subject:"):
        subject = first[len("subject:"):].strip()
        body = "\n".join(lines[1:]).strip()
    else:
        # Dạng B: dòng đầu = subject, phần còn lại = body
        subject = first
        body = "\n".join(lines[1:]).strip()

    if not body:
        raise ValueError(
            "Chỉ thấy 1 dòng. Nhập theo dạng:\n"
            "Subject: <tiêu đề>\n<nội dung email nhiều dòng>")
    return compose_manual(subject, body)


# ===========================================================================
# GỬI EMAIL — gọi lại mailer.send_email của timesheet
# ===========================================================================
def send_composed_email(email: dict, config) -> dict:
    """Gửi email đã soạn. GỌI LẠI mailer.send_email (dùng chung SMTP
    của timesheet). KHÔNG đính kèm file (email xin nghỉ không cần).

    to = boss_email; From/Bcc theo công tắc mail (mailer.get_mail_route).
    Trả dict kết quả từ mailer (message_id, sent_check).
    """
    import mailer  # import cục bộ, tránh phụ thuộc lúc load module

    # VALIDATE địa chỉ TRƯỚC khi gửi — chặn gửi nếu email settings sai
    addr_errors = validate_recipient(config)
    if addr_errors:
        raise ValueError(
            "Không gửi được — địa chỉ email trong settings.json sai:\n"
            + "\n".join(f"  • {e}" for e in addr_errors))

    to = config.get("boss_email")
    # From/Bcc do mailer.send_email quyết theo công tắc mail (công ty/Gmail)
    result = mailer.send_email(
        subject=email["subject"],
        body=email["body"],
        attachments=[],          # email xin nghỉ: không đính kèm
        to=to,
        config=config)
    log.info("compose_email đã gửi (%s): to=%s subject=%r",
             result.get("mode"), to, email["subject"])
    return {**result, "to": to,
            "subject": email["subject"], "body": email["body"]}


# ===========================================================================
# FORMAT — hiện email để người dùng xem trước khi gửi
# ===========================================================================
# Regex kiểm tra email cơ bản (đủ dùng, không cần RFC đầy đủ)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient(config) -> list[str]:
    """Kiểm tra boss_email trong settings có hợp lệ không.
    Trả list lỗi (rỗng = OK). Gọi TRƯỚC khi hiện preview và TRƯỚC khi gửi."""
    errors = []
    to = (config.get("boss_email") or "").strip()

    if not to:
        errors.append("Chưa cấu hình boss_email trong settings.json")
    elif not _EMAIL_RE.match(to):
        errors.append(f"boss_email '{to}' không đúng định dạng email")
    # Bcc không còn đọc từ settings — cố định theo công tắc mail
    # (công ty → Bcc email.rieng@gmail.com, Gmail → Bcc mail công ty).
    return errors


def format_preview(email: dict, config) -> str:
    """Định dạng email để hiện cho người dùng xác nhận trước khi gửi.
    Kèm cảnh báo nếu địa chỉ email trong settings không hợp lệ."""
    import mailer
    to = config.get("boss_email")
    route = mailer.get_mail_route(config)   # KHỚP cái sẽ gửi thật

    # Validate địa chỉ — cảnh báo ngay trong preview nếu sai
    addr_errors = validate_recipient(config)
    warn = ""
    if addr_errors:
        warn = ("\n⚠️ CẢNH BÁO ĐỊA CHỈ EMAIL:\n"
                + "\n".join(f"  • {e}" for e in addr_errors)
                + "\n  → Sửa settings.json trước khi gửi!\n")

    import leave_balance
    bal = leave_balance.compose_hint(config)
    bal = (bal + "\n\n") if bal else ""
    return warn + bal + (
        "📧 EMAIL NHÁP:\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Gửi qua: {route['label']}\n"
        f"From: {route['sender']}\n"
        f"To: {to}\n"
        f"Bcc: {route['bcc']}\n"
        f"Subject: {email['subject']}\n"
        "──────────────────\n"
        f"{email['body']}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Nhắn 'ok' để GỬI, nói mình sửa (vd 'thêm as communicated', "
        "'đổi ngày thành 20/9'), hoặc 'hủy' / /resetmail để HỦY "
        "(email sẽ KHÔNG được gửi)."
    )


def format_sent_confirmation(result: dict) -> str:
    """Thông báo xác nhận sau khi gửi thành công — ghi rõ email/subject/body."""
    return (
        "📤 ĐÃ GỬI — server mail đã NHẬN\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"From: {result.get('sender', '?')}\n"
        f"Tới: {result['to']}\n"
        f"Bcc: {result.get('bcc')}\n"
        f"Sent: {result.get('sent_check', '?')}\n"
        f"Subject: {result['subject']}\n"
        "──────────────────\n"
        f"{result['body']}\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# ===========================================================================
# SELF-TEST (không gọi AI thật — chỉ test logic đóng gói)
# ===========================================================================
if __name__ == "__main__":
    print("=" * 55)
    print("COMPOSE_EMAIL SELF-TEST (không gọi AI/SMTP thật)")
    print("=" * 55)

    # Test _validate_email_dict
    d = _validate_email_dict({
        "subject": "Leave Request",
        "body": "I'd like to take leave 10 Sept."})
    assert d["body"].lower().startswith(f"hi {_boss().lower()}")
    assert d["body"].rstrip().lower().endswith(_me().lower())
    print("✓ _validate_email_dict tự thêm Hi sếp + Regards/người dùng")

    # Test parse_manual_input dạng A
    m1 = parse_manual_input("Subject: Test\nHi sếp\nNội dung\nRegards\nngười dùng")
    assert m1["subject"] == "Test"
    assert "Nội dung" in m1["body"]
    print(f"✓ parse_manual dạng A: subject='{m1['subject']}'")

    # Test parse_manual_input dạng B
    m2 = parse_manual_input("Leave Request\nHi sếp\nContent here")
    assert m2["subject"] == "Leave Request"
    print(f"✓ parse_manual dạng B: subject='{m2['subject']}'")

    # Test thiếu body
    try:
        parse_manual_input("chỉ 1 dòng")
        print("✗ Phải raise khi thiếu body")
    except ValueError:
        print("✓ parse_manual raise khi thiếu body")

    # Test compose_manual
    cm = compose_manual("Subject X", "Body Y")
    assert cm["subject"] == "Subject X"
    print("✓ compose_manual đóng gói đúng")

    print("\n>>> ALL GREEN <<<")
