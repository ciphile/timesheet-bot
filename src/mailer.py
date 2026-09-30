"""
mailer.py — Gửi email timesheet qua Gmail (SMTP) + bảo đảm có trong Sent.

- Gửi qua smtp.gmail.com:587 STARTTLS, đăng nhập bằng App Password.
- Subject/Body dựng đúng template trong settings.json:
    Subject: "Timesheet up to 3rd July"   (ngày có ordinal: 1st/2nd/3rd/4th…)
    Body   : "…up to 3 July"              (KHÔNG ordinal)
- Tháng có Special Leave: chèn 1 câu tiếng Anh ngay SAU dòng
  "Please find attached…" (pattern trong settings).
- Sau khi gửi: kiểm tra bản sao trong folder Sent của Gmail qua IMAP
  (tìm theo Message-ID); Gmail thường tự lưu, nếu không thấy thì tự
  append vào. Tìm folder Sent theo cờ \\Sent nên tài khoản để tiếng
  Việt ("Thư đã gửi") vẫn chạy đúng.

Chạy thử trực tiếp (AN TOÀN — chỉ gửi cho CHÍNH BẠN, không đụng sếp):
    python thư mục timesheet\\src\\mailer.py
"""

import imaplib
import smtplib
import ssl
import time
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from config_loader import load_config
from log_setup import get_logger
from audit_log import audit

log = get_logger("mailer")

SMTP_TIMEOUT_SECONDS = 60
IMAP_HOST = "imap.gmail.com"
XLSX_MIME = ("application",
             "vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class MailerError(Exception):
    """Lỗi gửi mail — mail CHƯA đi. Thông báo tiếng Việt.
    .category (AUTH/NETWORK/SSL/RECIPIENT/SIZE/CONTENT/...) để bot gợi ý đúng."""

    def __init__(self, message: str, category: str = "OTHER"):
        super().__init__(message)
        self.category = category


# Loại lỗi mà đổi sang mail khác KHÔNG giúp được (lỗi nằm ở nội dung/địa chỉ)
_SWITCH_USELESS = {"RECIPIENT", "SIZE", "CONTENT", "ATTACH"}


def failure_message(reason: str, category: str, via: str) -> str:
    """Thông báo GỬI THẤT BẠI thống nhất cho mọi loại mail."""
    other = "/personalmailoff (về mail công ty)" if via == "Gmail" else \
            "/personalmailon (Gmail cá nhân)"
    lines = [f"❌ MAIL CHƯA GỬI ĐƯỢC ({via}) — sếp CHƯA nhận gì.",
             "━━━━━━━━━━━━━━━━━━", reason, "━━━━━━━━━━━━━━━━━━"]
    if category in _SWITCH_USELESS:
        lines.append("⚠️ Đổi sang mail khác KHÔNG giải quyết được lỗi này — sửa "
                     "nguyên nhân ở trên trước.")
    else:
        lines.append(f"👉 Gửi bằng mail khác: {other} → 'ok'. Email đang chờ vẫn "
                     "được GIỮ, bot hiện lại để bro gửi.")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Dựng subject / body theo template
# ---------------------------------------------------------------------

def ordinal(day: int) -> str:
    """3 -> '3rd', 11 -> '11th', 22 -> '22nd'…"""
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def build_subject(send_day: date, config) -> str:
    month = config.get("month_names")[send_day.month - 1]
    return config.get("email_subject_pattern").format(
        send_day_ordinal=ordinal(send_day.day), send_month=month)


_SL_NOLINK_DEFAULT = ("Please note I took {amount} of special leave on {sl_day} "
                      "{sl_month}.")


def build_special_leave_note(sl_date: date, ph_date, config, hours: float = 8.0) -> str:
    """Câu báo sếp về ngày Special Leave.
    ph_date = lễ-thứ-7 nó bù → dùng special_leave_note_pattern (settings).
    ph_date = None (nghỉ bù theo số dư nhập tay /updateleave, vd bù OT) → vẫn
    BÁO sếp ngày nghỉ bù, không nhắc lễ (sửa 25-Sep: trước bỏ qua, email không
    nhắc gì). Nửa ngày (<= 4,5h) → "half a day" thay "a day"."""
    month_names = config.get("month_names")
    half = float(hours or 8) <= 4.5
    amount = "half a day" if half else "a day"
    if ph_date is None:
        pat = (getattr(config, "settings", {}) or {}).get(
            "special_leave_note_nolink_pattern") or _SL_NOLINK_DEFAULT
        return pat.format(amount=amount, sl_day=sl_date.day,
                          sl_month=month_names[sl_date.month - 1])
    note = config.get("special_leave_note_pattern").format(
        sl_day=sl_date.day,
        sl_month=month_names[sl_date.month - 1],
        ph_date=ph_date.strftime("%d/%m/%Y"),
    )
    if half:
        note = note.replace("a day of special leave", "half a day of special leave")
    return note


def build_body(send_day: date, special_notes: list, config) -> str:
    """Ghép body từ email_body_lines; chèn các câu Special Leave (nếu
    có) ngay sau dòng 'Please find attached…'."""
    month = config.get("month_names")[send_day.month - 1]
    values = {
        "boss_name": config.get("boss_name"),
        "send_day": send_day.day,
        "send_month": month,
        "signature_name": config.get("signature_name"),
    }
    lines = [line.format(**values) for line in config.get("email_body_lines")]

    if special_notes:
        anchor = next(
            (i for i, line in enumerate(lines)
             if "please find attached" in line.lower()),
            None,
        )
        if anchor is None:
            # Template đổi mà không còn dòng neo — vẫn phải báo sếp:
            # chèn lên đầu thay vì lặng lẽ bỏ rơi.
            log.warning("Không thấy dòng 'Please find attached' trong "
                        "template — chèn ghi chú Special Leave lên đầu.")
            lines = list(special_notes) + lines
        else:
            lines[anchor + 1:anchor + 1] = list(special_notes)
    return "\n".join(lines)


# ---------------------------------------------------------------------
# CÔNG TẮC MAIL: công ty (mặc định) / Gmail cá nhân
# ---------------------------------------------------------------------
# Luật Bcc (người dùng quy định):
#   gửi bằng mail CÔNG TY  → luôn Bcc mail CÁ NHÂN
#   gửi bằng GMAIL cá nhân → luôn Bcc mail CÔNG TY
MAIL_MODE_COMPANY = "company"
MAIL_MODE_PERSONAL = "personal"
from config_loader import personal as _personal
BCC_WHEN_COMPANY = _personal("bcc_when_company")     # gửi mail công ty → Bcc (vd Gmail riêng)
BCC_WHEN_PERSONAL = _personal("company_email")       # gửi Gmail → Bcc mail công ty


def get_mail_mode() -> str:
    """Đọc công tắc trong state.json. Không có / lạ → MẶC ĐỊNH công ty."""
    try:
        import state as _st
        mode = _st.load_state().get("mail_mode") or MAIL_MODE_COMPANY
    except Exception:  # noqa: BLE001
        mode = MAIL_MODE_COMPANY
    return mode if mode in (MAIL_MODE_COMPANY, MAIL_MODE_PERSONAL) \
        else MAIL_MODE_COMPANY


def get_mail_route(config) -> dict:
    """Trả {"mode","sender","bcc","label"} theo công tắc hiện tại.
    Dùng chung cho: gửi thật, preview timesheet, preview email nghỉ phép,
    thông báo sau khi gửi → From/Bcc hiển thị luôn khớp cái gửi thật."""
    mode = get_mail_mode()
    if mode == MAIL_MODE_PERSONAL:
        try:
            sender = config.gmail_address
        except AttributeError:
            sender = "(chưa cấu hình GMAIL_ADDRESS)"
        return {"mode": mode, "sender": sender, "bcc": BCC_WHEN_PERSONAL,
                "label": "GMAIL CÁ NHÂN"}
    import company_mailer
    return {"mode": MAIL_MODE_COMPANY,
            "sender": company_mailer.COMPANY_ADDRESS,
            "bcc": BCC_WHEN_COMPANY, "label": "MAIL CÔNG TY"}


def build_email_preview(send_day, months_entries: dict, subject: str,
                        body: str, attachments: list, config) -> str:
    """Soạn NỘI DUNG EMAIL TIMESHEET để người dùng review TRƯỚC KHI GỬI.
    Khác /summary: đây là bản xem trước EMAIL thật sẽ gửi sếp, kèm
    tóm tắt D/E/F từng ngày để người dùng kiểm tra timesheet lần cuối.

    months_entries: {month_key: [entries]} — dữ liệu sẽ ghi Excel.
    """
    to = config.get("boss_email")
    route = get_mail_route(config)   # From/Bcc KHỚP cái sẽ gửi thật
    sender, bcc = route["sender"], route["bcc"]
    thu = ["T2","T3","T4","T5","T6","T7","CN"]
    lines = [
        "📧 EMAIL TIMESHEET SẼ GỬI SẾP — XEM TRƯỚC:",
        "═══════════════════",
        f"Gửi qua: {route['label']}",
        f"From : {sender}",
        f"To   : {to}",
        f"Bcc  : {bcc}",
        f"Cc   : (không có)",
        f"Subject: {subject}",
        "─── NỘI DUNG EMAIL (y chang gửi sếp) ───",
        body,
        "───────────────────",
        f"📎 Đính kèm: {', '.join(a.name for a in attachments)}",
        "═══════════════════",
        "📊 NỘI DUNG TIMESHEET (kiểm tra D/E/F lần cuối):",
    ]
    from datetime import date as _date
    for mk in sorted(months_entries):
        lines.append(f"\n── Tháng {mk} ──")
        by_day = {}
        for e in months_entries[mk]:
            d = e["date"] if isinstance(e["date"], _date) else _date.fromisoformat(str(e["date"]))
            by_day.setdefault(d, []).append(e)
        for d in sorted(by_day):
            tot = sum(float(x.get("hours") or 0) for x in by_day[d])
            lines.append(f"\n📅 {thu[d.weekday()]} {d.strftime('%d/%m/%Y')} "
                         f"— tổng {tot:g}h:")
            for i, e in enumerate(by_day[d], 1):
                h = float(e.get("hours") or 0)
                proj = e.get("project", "") or "(trống)"
                task = e.get("task", "") or "(trống)"
                desc = e.get("description", "") or "(trống)"
                # Mỗi cột 1 DÒNG RIÊNG — ticket dài (15 cái) vẫn hiện ĐỦ,
                # không cắt, không giới hạn độ rộng.
                lines.append(f"  • Task {i} ({h:g}h):")
                lines.append(f"      D (Project) : {proj}")
                lines.append(f"      E (Task)    : {task}")
                lines.append(f"      F (Desc)    : {desc}")
    lines += [
        "═══════════════════",
        "Nhắn 'ok' để GỬI cho sếp, hoặc 'hủy' / /resetmailts để HỦY "
        "và sửa lại timesheet (email sẽ KHÔNG được gửi).",
        "✍️ Muốn tự viết nội dung email (nhắn thêm gì cho sếp): /manualmail",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Gửi mail
# ---------------------------------------------------------------------

def _build_message(subject: str, body: str, attachments: list,
                   sender: str, to: str, bcc) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    if bcc:
        # smtplib.send_message dùng Bcc để định tuyến rồi TỰ GỠ header
        # này trước khi truyền đi — người nhận To không thấy Bcc.
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)

    for path in attachments:
        path = Path(path)
        if not path.exists():
            raise MailerError(f"File đính kèm không tồn tại: {path}")
        maintype, subtype = XLSX_MIME
        msg.add_attachment(path.read_bytes(), maintype=maintype,
                           subtype=subtype, filename=path.name)
    return msg


def send_email(subject: str, body: str, attachments: list, to: str,
               config, bcc=None, ensure_sent: bool = True) -> dict:
    """BỘ ĐỊNH TUYẾN — mọi nơi gửi mail (timesheet, gởi lại, email nghỉ
    phép) đều gọi hàm này. Chọn mail CÔNG TY (mặc định) hoặc GMAIL cá
    nhân theo công tắc /personalmailon /personalmailoff.

    Tham số bcc của nơi gọi bị BỎ QUA: Bcc luôn theo luật của route
    (công ty→Bcc cá nhân, Gmail→Bcc công ty).
    KHÔNG tự chuyển sang Gmail khi mail công ty lỗi (tránh sếp nhận mail
    từ địa chỉ lạ) — báo lỗi + gợi ý /personalmailon.

    Trả {"message_id","sent_check","mode","sender","bcc"}.
    Lỗi → raise MailerError (nơi gọi đang bắt MailerError sẵn)."""
    route = get_mail_route(config)
    if bcc and bcc != route["bcc"]:
        log.debug("Bỏ bcc nơi gọi (%s) — dùng bcc theo route (%s).",
                  bcc, route["bcc"])

    if route["mode"] == MAIL_MODE_PERSONAL:
        res = _send_via_gmail(subject, body, attachments, to, config,
                              bcc=route["bcc"], ensure_sent=ensure_sent)
        return {**res, "mode": route["mode"], "sender": route["sender"],
                "bcc": route["bcc"], "subject": subject,
                "sent_at": datetime.now().isoformat(timespec="seconds")}

    import company_mailer
    try:
        r = company_mailer.send_email_company(
            subject, body, attachments, to, bcc=route["bcc"])
    except company_mailer.CompanyMailError as e:
        audit("MAIL_FAILED", f"company [{e.category}]: {e}")
        raise MailerError(failure_message(str(e), e.category, "mail công ty"),
                          e.category)
    names = [Path(p).name for p in attachments]
    audit("MAIL_SENT", f"company; to={to}; bcc={r['bcc']}; "
                       f"subject={subject}; files={names}")
    sent_check = (f"Sent ({r['sent_folder']}) mail công ty"
                  if r["saved_to_sent"] else f"⚠️ {r['sent_warning']}")
    if r.get("bcc_warnings"):
        sent_check += " · ⚠️ " + "; ".join(r["bcc_warnings"])
    return {"message_id": r["message_id"], "sent_check": sent_check,
            "mode": route["mode"], "sender": route["sender"],
            "bcc": r["bcc"], "subject": subject,
            "sent_at": datetime.now().isoformat(timespec="seconds")}


def _send_via_gmail(subject: str, body: str, attachments: list, to: str,
                    config, bcc=None, ensure_sent: bool = True) -> dict:
    """Gửi 1 email bằng GMAIL cá nhân (logic cũ, giữ nguyên).
    Trả về {"message_id", "sent_check"}.
    Lỗi -> raise MailerError với hướng dẫn tiếng Việt."""
    import mail_errors
    try:
        mail_errors.precheck_attachments(attachments)
    except mail_errors.SendFailed as e:
        raise MailerError(failure_message(str(e), e.category, "Gmail"), e.category)
    sender = config.gmail_address
    msg = _build_message(subject, body, attachments, sender, to, bcc)
    names = [Path(p).name for p in attachments]
    log.info("Gửi mail: to=%s bcc=%s | subject=%r | đính kèm=%s",
             to, bcc, subject, names)

    # QUAN TRỌNG: server Gmail XÁC NHẬN đã nhận mail (accepted) ngay
    # khi send_message() trả về không lỗi — TRƯỚC KHI đóng kết nối.
    # Nếu để smtplib.quit() (chạy lúc "with" thoát khối) ném lỗi mạng
    # SAU thời điểm đó, mà code coi đó là "gửi thất bại", người dùng sẽ
    # tưởng chưa gửi rồi bấm "ok" lại lần nữa -> SẾP NHẬN 2 BẢN. Nên
    # tách riêng: lỗi TRƯỚC/TRONG send_message = thật sự chưa gửi,
    # được phép raise; lỗi lúc ĐÓNG kết nối (sau khi đã gửi xong) chỉ
    # log cảnh báo, KHÔNG raise, vì mail đã tới tay sếp rồi.
    sent_ok = False
    smtp = None
    try:
        context = ssl.create_default_context()
        smtp = smtplib.SMTP(config.get("smtp_host"), config.get("smtp_port"),
                            timeout=SMTP_TIMEOUT_SECONDS)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.login(sender, config.gmail_app_password)
        refused = smtp.send_message(msg)
        sent_ok = True   # <- server đã accept, mail COI NHƯ ĐÃ GỬI từ đây
    except (smtplib.SMTPException, OSError) as e:
        if not sent_ok:
            f = mail_errors.classify(e, config.get("smtp_host"),
                                     config.get("smtp_port"), "Gmail")
            if f.category == "AUTH":
                f = mail_errors.SendFailed(
                    str(f) + "\nGmail: thường do App Password sai / bị thu hồi "
                    "sau khi đổi mật khẩu chính → tạo App Password mới.", "AUTH")
            audit("MAIL_FAILED", f"gmail [{f.category}]: {e}")
            log.exception("Gửi mail thất bại (chưa gửi được).")
            raise MailerError(failure_message(str(f), f.category, "Gmail"),
                              f.category)
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception as e:  # noqa: BLE001 — KHÔNG được biến
                # lỗi lúc đóng kết nối thành "gửi thất bại" nếu mail
                # đã accept ở trên rồi.
                log.warning("Đóng kết nối SMTP có trục trặc nhỏ sau "
                           "khi mail đã gửi xong (%s) — bỏ qua, mail "
                           "vẫn tới nơi bình thường.", e)

    # send_message không báo lỗi nếu còn ≥1 người nhận được nhận → tự kiểm:
    # SẾP (To) bị từ chối = THẤT BẠI (trước 24-Sep: báo thành công!)
    try:
        bcc_warn = mail_errors.check_refused(refused, to, "Gmail")
    except mail_errors.SendFailed as e:
        audit("MAIL_FAILED", f"gmail [RECIPIENT]: {refused}")
        raise MailerError(failure_message(str(e), e.category, "Gmail"), e.category)
    audit("MAIL_SENT", f"to={to}; subject={subject}; files={names}")
    log.info("SMTP nhận mail thành công (Message-ID %s).", msg["Message-ID"])

    sent_check = "skipped"
    if ensure_sent:
        sent_check = _ensure_in_sent(msg, config)
    if bcc_warn:
        sent_check = f"{sent_check} · ⚠️ " + "; ".join(bcc_warn)
    return {"message_id": msg["Message-ID"], "sent_check": sent_check}


# ---------------------------------------------------------------------
# Bảo đảm có trong folder Sent
# ---------------------------------------------------------------------

def _find_sent_folder(imap) -> str:
    """Tìm folder mang cờ \\Sent (chịu được tên tiếng Việt 'Thư đã gửi')."""
    status, listing = imap.list()
    if status == "OK":
        for raw in listing:
            line = raw.decode("utf-8", errors="replace")
            if "\\Sent" in line:
                return line.rsplit(' "', 1)[-1].strip('"')
    return "[Gmail]/Sent Mail"   # dự phòng tên mặc định tiếng Anh


def _ensure_in_sent(msg: EmailMessage, config) -> str:
    """Kiểm tra mail đã nằm trong Sent chưa (Gmail thường tự lưu khi
    gửi qua SMTP); chưa thấy thì tự append. Bước này KHÔNG được phép
    làm hỏng việc gửi — lỗi gì cũng chỉ log + trả trạng thái."""
    try:
        time.sleep(5)   # cho Gmail vài giây để tự lưu bản Sent
        with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
            imap.login(config.gmail_address, config.gmail_app_password)
            folder = _find_sent_folder(imap)
            imap.select(f'"{folder}"', readonly=True)
            status, found = imap.search(
                None, "HEADER", "Message-ID", msg["Message-ID"])
            if status == "OK" and found and found[0].split():
                log.info("Đã thấy mail trong Sent (%s).", folder)
                return "already_in_sent"
            imap.append(f'"{folder}"', "\\Seen",
                        imaplib.Time2Internaldate(time.time()),
                        msg.as_bytes())
            log.info("Gmail chưa tự lưu — đã append bản sao vào %s.", folder)
            audit("MAIL_APPENDED_SENT", msg["Message-ID"])
            return "appended"
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("Không kiểm tra được folder Sent (%s: %s) — mail VẪN "
                    "ĐÃ GỬI thành công.", type(e).__name__, e)
        return f"check_failed: {type(e).__name__}"


# ---------------------------------------------------------------------
# Self-test: gửi thử về CHÍNH MÌNH (tuyệt đối không đụng sếp)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    cfg = load_config()
    me = cfg.gmail_address
    today = date.today()
    print(f"Gửi mail THỬ về chính bạn ({me}) — sếp KHÔNG nhận gì hết…")

    subject = "[TEST] " + build_subject(today, cfg)
    note = build_special_leave_note(date(2026, 3, 23), date(2026, 3, 21), cfg)
    body = build_body(today, [note], cfg)
    print("-" * 50)
    print("Subject:", subject)
    print(body)
    print("-" * 50)

    result = send_email(subject, body, attachments=[], to=me, config=cfg)
    print("KẾT QUẢ: đã gửi. Message-ID:", result["message_id"])
    print("Kiểm tra Sent:", result["sent_check"])
    print("Mở Gmail: hộp thư đến PHẢI có mail này, và mục Sent cũng phải có.")
