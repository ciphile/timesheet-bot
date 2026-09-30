"""
mail_errors.py — Bắt & giải thích lỗi gửi mail (24-Sep-2026).

Dùng CHUNG cho mail công ty (company_mailer) và Gmail cá nhân (mailer).

Lỗi TỨC THỜI (lúc gửi): sai mật khẩu, mạng chặn cổng, SSL, server từ chối
người nhận, file quá lớn / bị lọc virus → bắt 100%, classify() dịch ra tiếng
Việt + mã lỗi gốc + cách xử lý. Mail CHƯA đi.

(Chức năng dò mail DỘI NGƯỢC sau khi gửi đã bị xóa theo yêu cầu của người dùng 25-Sep.
"250 OK" = server đã nhận, bot không kiểm tra thêm sếp có nhận được hay không.)
"""

from __future__ import annotations

import email
import imaplib
import re
import smtplib
import socket
import ssl
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from pathlib import Path

from log_setup import get_logger

log = get_logger("mail_errors")

MAX_ATTACH_MB = 20            # server thường giới hạn 10–25MB
_BLOCKED_EXT = {".xlsm", ".xlsb", ".exe", ".bat", ".js", ".vbs"}


class SendFailed(Exception):
    """Gửi THẤT BẠI — mail CHƯA tới sếp. .category để bot quyết cách báo."""

    def __init__(self, message: str, category: str = "OTHER"):
        super().__init__(message)
        self.category = category


# ---------------------------------------------------------------------
# 1) Lỗi TỨC THỜI
# ---------------------------------------------------------------------
def _code_msg(e) -> str:
    code = getattr(e, "smtp_code", None)
    msg = getattr(e, "smtp_error", b"")
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    return f"mã {code}: {msg.strip()}" if code else f"{type(e).__name__}: {e}"


def classify(e: Exception, host: str, port: int, label: str) -> SendFailed:
    """Dịch lỗi kỹ thuật → SendFailed tiếng Việt (lý do + mã gốc + cách xử lý).
    label: "mail công ty" / "Gmail". THỨ TỰ KIỂM QUAN TRỌNG: các lỗi SMTP là
    lớp con của OSError → phải xét TRƯỚC nhánh lỗi mạng."""
    low = str(e).lower()
    if isinstance(e, smtplib.SMTPAuthenticationError) or (
            isinstance(e, imaplib.IMAP4.error) and ("auth" in low or "login" in low)):
        return SendFailed(
            f"Đăng nhập {label} BỊ TỪ CHỐI ({_code_msg(e)}).\n"
            "Nguyên nhân: sai mật khẩu, mật khẩu vừa đổi, hoặc tài khoản bị khóa.\n"
            "Cách xử lý: kiểm tra mật khẩu trong config\\secrets.env "
            "(COMPANY_MAIL_PASSWORD / GMAIL_APP_PASSWORD).", "AUTH")
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return refused_error(e.recipients, label)
    if isinstance(e, smtplib.SMTPSenderRefused):
        return SendFailed(
            f"Server {label} TỪ CHỐI địa chỉ người gửi ({_code_msg(e)}).\n"
            "Nguyên nhân: tài khoản bị hạn chế gửi / bị đánh dấu spam.", "SENDER")
    if isinstance(e, smtplib.SMTPDataError):
        code = getattr(e, "smtp_code", 0) or 0
        if code == 552 or "size" in low:
            return SendFailed(
                f"Server {label} TỪ CHỐI vì mail QUÁ LỚN ({_code_msg(e)}).\n"
                "Nguyên nhân: file đính kèm vượt giới hạn dung lượng của server.", "SIZE")
        if "virus" in low or "spam" in low or "policy" in low or "content" in low:
            return SendFailed(
                f"Bộ lọc của server {label} CHẶN mail ({_code_msg(e)}).\n"
                "Nguyên nhân: nghi virus/spam, hoặc loại file đính kèm bị cấm.", "CONTENT")
        return SendFailed(f"Server {label} từ chối nội dung mail ({_code_msg(e)}).", "DATA")
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return SendFailed(
            f"Server {label} NGẮT KẾT NỐI giữa chừng ({e}).\n"
            "Nguyên nhân: mạng chập chờn hoặc server quá tải.", "NETWORK")
    if isinstance(e, smtplib.SMTPResponseException):
        return SendFailed(f"Server {label} báo lỗi ({_code_msg(e)}).", "SMTP")
    if isinstance(e, ssl.SSLCertVerificationError):
        return SendFailed(
            f"Chứng chỉ bảo mật SSL của {host} KHÔNG HỢP LỆ ({e.verify_message or e}).\n"
            "Nguyên nhân: chứng chỉ tự ký hoặc đã hết hạn chưa gia hạn.\n"
            "Cách xử lý: báo IT công ty. Bot KHÔNG tự tắt kiểm tra bảo mật.", "SSL")
    if isinstance(e, ssl.SSLError):
        return SendFailed(
            f"Lỗi bắt tay SSL với {host}:{port} ({e}).\n"
            f"Nguyên nhân: cổng {port} có thể không dùng SSL trực tiếp mà cần "
            "STARTTLS, hoặc mạng đang chặn/giả mạo kết nối bảo mật.", "SSL")
    if isinstance(e, socket.gaierror):
        return SendFailed(
            f"KHÔNG tìm thấy server {host} (lỗi DNS: {e}).\n"
            "Nguyên nhân: mất Internet, hoặc tên server bị gõ sai.", "NETWORK")
    if isinstance(e, (socket.timeout, TimeoutError)):
        return SendFailed(
            f"Kết nối tới {host}:{port} QUÁ THỜI GIAN chờ ({e}).\n"
            f"Nguyên nhân: mất mạng, hoặc mạng (wifi quán cà phê / khách sạn / "
            f"công ty khác) CHẶN cổng {port}.", "NETWORK")
    if isinstance(e, ConnectionRefusedError):
        return SendFailed(
            f"{host}:{port} TỪ CHỐI kết nối ({e}).\n"
            f"Nguyên nhân: tường lửa chặn cổng {port}, hoặc server đang tắt.", "NETWORK")
    if isinstance(e, OSError):
        return SendFailed(f"Lỗi mạng khi nối tới {host}:{port} ({e}).", "NETWORK")
    return SendFailed(f"{type(e).__name__}: {e}", "OTHER")


def refused_error(refused: dict, label: str) -> SendFailed:
    parts = []
    relay = False
    for addr, (code, msg) in refused.items():
        m = msg.decode("utf-8", "replace") if isinstance(msg, bytes) else str(msg)
        relay = relay or "relay" in m.lower()
        parts.append(f"{addr} (mã {code}: {m.strip()})")
    why = ("server CHỈ cho gửi trong nội bộ công ty (Relay denied)" if relay else
           "địa chỉ gõ sai / không tồn tại, hoặc bị chính sách server chặn")
    return SendFailed(
        f"Server {label} KHÔNG NHẬN địa chỉ người nhận: {'; '.join(parts)}.\n"
        f"Nguyên nhân: {why}.\n"
        "Cách xử lý: kiểm tra boss_email trong config\\settings.json.", "RECIPIENT")


def check_refused(refused: dict, to: str, label: str) -> list[str]:
    """send_message() KHÔNG báo lỗi nếu CÒN ÍT NHẤT 1 người nhận được chấp
    nhận — nó trả dict những người bị từ chối. Trước 24-Sep bot bỏ qua →
    sếp (To) bị từ chối mà Bcc vẫn nhận → bot báo GỬI THÀNH CÔNG.
    Nay: To bị từ chối → raise SendFailed. Chỉ Bcc bị từ chối → trả cảnh báo."""
    if not refused:
        return []
    to_l = (to or "").strip().lower()
    if any(a.strip().lower() == to_l for a in refused):
        raise refused_error(refused, label)
    return [f"Bcc {a} bị từ chối (mã {c})" for a, (c, _) in refused.items()]


def precheck_attachments(paths: list) -> None:
    """Chặn TRƯỚC khi gửi: file không tồn tại, loại file hay bị lọc (.xlsm
    chứa macro...), tổng dung lượng quá lớn."""
    total = 0
    for p in paths:
        p = Path(p)
        if not p.exists():
            raise SendFailed(f"Không thấy file đính kèm {p.name}.", "ATTACH")
        if p.suffix.lower() in _BLOCKED_EXT:
            raise SendFailed(
                f"File {p.name} có đuôi {p.suffix} — mail server hay chặn (chứa "
                "macro/thực thi). Timesheet phải là .xlsx.", "CONTENT")
        total += p.stat().st_size
    if total > MAX_ATTACH_MB * 1024 * 1024:
        raise SendFailed(
            f"File đính kèm tổng {total / 1024 / 1024:.1f}MB > {MAX_ATTACH_MB}MB — "
            "server sẽ từ chối. Kiểm tra file Excel có bị phình bất thường.", "SIZE")
