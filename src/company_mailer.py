"""
company_mailer.py — Gửi mail bằng EMAIL CÔNG TY (ten.ban@congty.com).

BƯỚC 1 (hiện tại): module độc lập + chế độ test. CHƯA nối vào bot.
Khi test OK mới ráp vào timesheet + email nghỉ phép (công tắc
/personalmailon /personalmailoff).

Khác Gmail ở 1 điểm QUAN TRỌNG:
  Gmail tự lưu thư đã gửi vào "Sent". Server mail công ty (SMTP thường)
  thì KHÔNG — gửi qua SMTP xong, thư không tự nằm trong Sent. Nên sau
  khi gửi, module này dùng IMAP APPEND để CẤT 1 bản vào thư mục Sent,
  giống Outlook/Thunderbird làm.

Mật khẩu: đọc từ thư mục timesheet\\config\\secrets.env, dòng
  COMPANY_MAIL_PASSWORD=...
KHÔNG bao giờ in / log mật khẩu.

Cách test (chạy trong thư mục timesheet\\src):
  python company_mailer.py --check    → chỉ đăng nhập SMTP + IMAP, liệt kê
                                        thư mục, KHÔNG gửi gì (chạy trước)
  python company_mailer.py --test     → gửi 1 mail test tới email.rieng@gmail.com
                                        + lưu vào Sent

Cập nhật: 23-Sep-2026
"""

from __future__ import annotations

import imaplib
import os
import re
import smtplib
import socket
import ssl
import sys
import time
from email.utils import formataddr
from pathlib import Path

from log_setup import get_logger

log = get_logger("company_mailer")

# ---------------------------------------------------------------------
# Cấu hình mail công ty — ĐỌC TỪ config/settings.json (mỗi người điền của mình)
# ---------------------------------------------------------------------
from config_loader import personal as _personal
COMPANY_ADDRESS = _personal("company_email")
COMPANY_DISPLAY_NAME = _personal("company_display_name", _personal("signature_name"))
MAIL_HOST = _personal("company_mail_host")
SMTP_PORT = 465        # SSL
IMAP_PORT = 993        # SSL
TIMEOUT_SEC = 30

# Khi gửi bằng mail công ty → Bcc địa chỉ "bcc_when_company" (để trống = không Bcc)
DEFAULT_BCC_WHEN_COMPANY = _personal("bcc_when_company")
TEST_RECIPIENT = DEFAULT_BCC_WHEN_COMPANY or COMPANY_ADDRESS

# Tên thư mục Sent hay gặp trên các loại server (cPanel/Dovecot/Exchange)
_SENT_CANDIDATES = ["Sent", "INBOX.Sent", "Sent Items", "INBOX.Sent Items",
                    "Sent Messages", "INBOX.Sent Messages", "Sent Mail"]

SECRETS_FILE = Path(__file__).resolve().parent.parent / "config" / "secrets.env"


import mail_errors


class CompanyMailError(mail_errors.SendFailed):
    """Lỗi gửi mail công ty — thông báo tiếng Việt, in ra là hiểu.
    .category: AUTH / NETWORK / SSL / RECIPIENT / SIZE / CONTENT / ..."""

    def __init__(self, message: str, category: str = "OTHER"):
        super().__init__(message, category)


# ---------------------------------------------------------------------
# Mật khẩu
# ---------------------------------------------------------------------
def _require_company_config() -> None:
    if not COMPANY_ADDRESS or not MAIL_HOST:
        raise CompanyMailError(
            "Chưa cấu hình mail công ty. Mở config\\settings.json, điền "
            "\"company_email\" và \"company_mail_host\" rồi khởi động lại bot.\n"
            "Hoặc gõ /personalmailon để gửi bằng Gmail cá nhân.", "AUTH")


def _get_password() -> str:
    """Đọc COMPANY_MAIL_PASSWORD từ secrets.env (qua biến môi trường)."""
    _require_company_config()
    try:
        from dotenv import load_dotenv
        load_dotenv(SECRETS_FILE)
    except ImportError:
        pass
    pw = os.environ.get("COMPANY_MAIL_PASSWORD", "").strip()
    if not pw or pw.upper().startswith("PASTE") or pw == "xxx":
        raise CompanyMailError(
            f"Chưa có mật khẩu email công ty.\n"
            f"Mở {SECRETS_FILE} bằng Notepad, thêm 1 dòng:\n"
            f"  COMPANY_MAIL_PASSWORD=mat_khau_email_cong_ty\n"
            f"(không dấu nháy, không khoảng trắng 2 bên dấu =), lưu lại.")
    return pw


def _ssl_context() -> ssl.SSLContext:
    # Luôn kiểm tra chứng chỉ server — KHÔNG tắt verify cho tiện.
    return ssl.create_default_context()


def _explain(e: Exception, stage: str) -> CompanyMailError:
    """Dịch lỗi kỹ thuật → tiếng Việt (dùng bộ phân loại chung mail_errors)."""
    port = SMTP_PORT if stage == "SMTP" else IMAP_PORT
    f = mail_errors.classify(e, MAIL_HOST, port, "mail công ty")
    return CompanyMailError(f"[{stage}] {f}", f.category)


# ---------------------------------------------------------------------
# Thư mục Sent
# ---------------------------------------------------------------------
def _list_folders(imap: imaplib.IMAP4_SSL) -> list[tuple[str, str]]:
    """Trả [(flags, tên_thư_mục)] từ lệnh IMAP LIST."""
    typ, data = imap.list()
    out = []
    if typ != "OK" or not data:
        return out
    for raw in data:
        if raw is None:
            continue
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        # dạng: (\HasNoChildren \Sent) "." "INBOX.Sent"
        m = re.match(r'\((?P<flags>[^)]*)\)\s+"?(?P<delim>[^"\s]*)"?\s+(?P<name>.+)$', line)
        if not m:
            continue
        name = m.group("name").strip().strip('"')
        out.append((m.group("flags"), name))
    return out


def find_sent_folder(imap: imaplib.IMAP4_SSL) -> str | None:
    """Tìm thư mục Sent: ưu tiên cờ \\Sent do server khai báo, sau đó
    dò theo tên thường gặp. Không tìm thấy → None (KHÔNG tự tạo)."""
    folders = _list_folders(imap)
    for flags, name in folders:
        if "\\sent" in flags.lower():
            return name
    names_lower = {n.lower(): n for _, n in folders}
    for cand in _SENT_CANDIDATES:
        if cand.lower() in names_lower:
            return names_lower[cand.lower()]
    return None


def _quote_mailbox(name: str) -> str:
    return '"' + name.replace('"', '\\"') + '"' if " " in name else name


# ---------------------------------------------------------------------
# Gửi
# ---------------------------------------------------------------------
def send_email_company(subject: str, body: str, attachments: list, to: str,
                       bcc: str | None = DEFAULT_BCC_WHEN_COMPANY) -> dict:
    """Gửi 1 email bằng mail công ty, rồi lưu bản sao vào Sent.

    Trả {"message_id", "sender", "to", "bcc", "sent_folder",
         "saved_to_sent": bool, "sent_warning": str}.
    Gửi lỗi → raise CompanyMailError (mail CHƯA đi).
    Gửi OK nhưng lưu Sent lỗi → KHÔNG raise (mail đã tới sếp), trả
    saved_to_sent=False + sent_warning để báo người dùng.
    """
    import mailer  # dùng lại cách dựng thư + đính kèm xlsx của mailer.py

    password = _get_password()
    # Bcc trùng người nhận thì bỏ (tránh 2 bản vào cùng hộp thư)
    if bcc and bcc.strip().lower() == (to or "").strip().lower():
        bcc = None

    try:                                   # chặn TRƯỚC: file quá lớn / .xlsm...
        mail_errors.precheck_attachments(attachments)
    except mail_errors.SendFailed as e:
        raise CompanyMailError(str(e), e.category)
    sender = formataddr((COMPANY_DISPLAY_NAME, COMPANY_ADDRESS))
    msg = mailer._build_message(subject, body, attachments, sender, to, bcc)
    names = [Path(p).name for p in attachments]
    log.info("[company] Gửi mail: to=%s bcc=%s | subject=%r | đính kèm=%s",
             to, bcc, subject, names)

    # 1) SMTP — gửi thật. Tách lỗi TRƯỚC/TRONG send_message (mail CHƯA đi →
    # raise) với lỗi lúc ĐÓNG kết nối SAU khi server đã nhận (mail ĐÃ đi →
    # chỉ log). Trước 24-Sep dùng "with": rớt mạng lúc quit() sau khi đã gửi
    # → báo thất bại → người dùng gửi lại → SẾP NHẬN 2 BẢN.
    smtp = None
    try:
        smtp = smtplib.SMTP_SSL(MAIL_HOST, SMTP_PORT, context=_ssl_context(),
                                timeout=TIMEOUT_SEC)
        smtp.login(COMPANY_ADDRESS, password)
        # send_message tự bỏ header Bcc khi truyền đi (người nhận To
        # không thấy Bcc); msg gốc vẫn giữ Bcc để bản trong Sent đủ.
        refused = smtp.send_message(msg)
    except Exception as e:  # noqa: BLE001
        err = _explain(e, "SMTP")
        log.error("[company] Gửi thất bại: %s", err)
        raise err from e
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception as e:  # noqa: BLE001 — mail (nếu đã nhận) vẫn đi
                log.warning("[company] Đóng kết nối SMTP trục trặc (%s) — bỏ qua.", e)
    # send_message KHÔNG báo lỗi nếu còn ≥ 1 người nhận được chấp nhận → phải
    # tự kiểm: SẾP (To) bị từ chối = GỬI THẤT BẠI (trước 24-Sep: báo thành công!)
    try:
        bcc_warn = mail_errors.check_refused(refused, to, "mail công ty")
    except mail_errors.SendFailed as e:
        log.error("[company] Người nhận chính bị từ chối: %s", refused)
        raise CompanyMailError(str(e), e.category)

    result = {"bcc_warnings": bcc_warn,
              "message_id": msg["Message-ID"], "sender": COMPANY_ADDRESS,
              "to": to, "bcc": bcc, "sent_folder": None,
              "saved_to_sent": False, "sent_warning": ""}

    # 2) IMAP — cất bản sao vào Sent (không làm hỏng việc đã gửi)
    try:
        with imaplib.IMAP4_SSL(MAIL_HOST, IMAP_PORT,
                               ssl_context=_ssl_context(),
                               timeout=TIMEOUT_SEC) as imap:
            imap.login(COMPANY_ADDRESS, password)
            folder = find_sent_folder(imap)
            if not folder:
                result["sent_warning"] = (
                    "Mail ĐÃ GỬI nhưng không tìm thấy thư mục Sent để lưu "
                    "bản sao — chạy 'python company_mailer.py --check' xem "
                    "danh sách thư mục.")
            else:
                typ, _ = imap.append(
                    _quote_mailbox(folder), "(\\Seen)",
                    imaplib.Time2Internaldate(time.time()),
                    msg.as_bytes())
                result["sent_folder"] = folder
                result["saved_to_sent"] = (typ == "OK")
                if typ != "OK":
                    result["sent_warning"] = (
                        f"Mail ĐÃ GỬI nhưng lưu vào '{folder}' thất bại ({typ}).")
    except Exception as e:  # noqa: BLE001
        result["sent_warning"] = (
            f"Mail ĐÃ GỬI nhưng lưu bản sao vào Sent lỗi: {_explain(e, 'IMAP')}")

    if result["sent_warning"]:
        log.warning("[company] %s", result["sent_warning"])
    else:
        log.info("[company] Đã gửi + lưu vào Sent '%s'.", result["sent_folder"])
    return result


# ---------------------------------------------------------------------
# Kiểm tra kết nối (không gửi gì)
# ---------------------------------------------------------------------
def check_connection() -> dict:
    """Đăng nhập SMTP + IMAP, tìm thư mục Sent. KHÔNG gửi mail nào."""
    password = _get_password()
    out = {"smtp_ok": False, "imap_ok": False, "sent_folder": None,
           "folders": []}
    try:
        with smtplib.SMTP_SSL(MAIL_HOST, SMTP_PORT, context=_ssl_context(),
                              timeout=TIMEOUT_SEC) as smtp:
            smtp.login(COMPANY_ADDRESS, password)
            out["smtp_ok"] = True
    except Exception as e:  # noqa: BLE001
        raise _explain(e, "SMTP") from e
    try:
        with imaplib.IMAP4_SSL(MAIL_HOST, IMAP_PORT,
                               ssl_context=_ssl_context(),
                               timeout=TIMEOUT_SEC) as imap:
            imap.login(COMPANY_ADDRESS, password)
            out["imap_ok"] = True
            out["folders"] = [n for _, n in _list_folders(imap)]
            out["sent_folder"] = find_sent_folder(imap)
    except Exception as e:  # noqa: BLE001
        raise _explain(e, "IMAP") from e
    return out


# ---------------------------------------------------------------------
# Chạy tay để test
# ---------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--check"
    print("=" * 55)
    print(f"COMPANY MAILER — {mode}")
    print(f"Tài khoản: {COMPANY_ADDRESS}  |  server: {MAIL_HOST}")
    print("=" * 55)
    try:
        if mode == "--check":
            r = check_connection()
            print(f"✓ SMTP đăng nhập OK (cổng {SMTP_PORT})")
            print(f"✓ IMAP đăng nhập OK (cổng {IMAP_PORT})")
            print(f"  Thư mục trên server: {', '.join(r['folders']) or '(trống)'}")
            if r["sent_folder"]:
                print(f"✓ Thư mục Sent: {r['sent_folder']}")
            else:
                print("✗ KHÔNG tìm thấy thư mục Sent — gửi được nhưng "
                      "không lưu được bản sao. Báo lại tên thư mục ở trên.")
            print("\nChưa gửi mail nào. Nếu OK → chạy: python company_mailer.py --test")
            return 0
        if mode == "--test":
            stamp = time.strftime("%d/%m/%Y %H:%M")
            r = send_email_company(
                subject=f"[TEST] Timesheet bot - company mail {stamp}",
                body=("Hi,\n\nThis is a test email sent by the timesheet bot "
                      "using the company mail account.\n\nRegards\n" + _personal("signature_name", "")),
                attachments=[], to=TEST_RECIPIENT)
            print(f"✓ ĐÃ GỬI tới {r['to']} (bcc: {r['bcc'] or 'không'})")
            if r["saved_to_sent"]:
                print(f"✓ Đã lưu bản sao vào thư mục Sent: {r['sent_folder']}")
            else:
                print(f"⚠️ {r['sent_warning']}")
            print(f"\nKiểm tra: (1) hộp thư {TEST_RECIPIENT} (xem cả Spam),"
                  "\n          (2) Sent của mail công ty (webmail/Outlook).")
            return 0
        print("Dùng: python company_mailer.py --check | --test")
        return 2
    except CompanyMailError as e:
        print(f"✗ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
