"""
bot.py — Entry #1: bot Telegram. (BẢN 2 — hội thoại đầy đủ)

Giữ nguyên từ bản 1.1: whitelist chat_id, khóa chống chạy trùng,
tự tắt theo bot_stop_time, log + audit, error handler toàn cục,
QUY TẮC DI THƯ, chạy nền qua start_bot.vbs.

Thêm ở bản 2 (cổng review + hội thoại thứ 6 — PROJECT.md mục 7, 9b):
- "ok" khi có bản nháp    -> CHỐT GỬI (ghi file + bản giao + mail sếp
                             + câu "Timesheet đã gởi email cho sếp bự
                             thành công")
- "khoan gởi"             -> bật chế độ giữ; "bỏ khoan" -> tắt
- "gởi timesheet (tới hôm nay)" -> soạn nháp SỚM ngay hôm nay
- Đang chờ bổ sung (bot đã hỏi thiếu ngày) -> câu trả lời được lưu
  thành ghi chú rồi soạn lại nháp, lặp tới khi đủ
- Đang có bản nháp -> mọi tin nhắn khác = LỆNH SỬA nháp (nói tự nhiên)
- /status -> tình hình; còn lại -> ghi chú công việc như bản 1

Chạy tay:  python bot.py (trong thư mục src)   (dừng: Ctrl+C)
"""

import asyncio
import rule_parser as _rule_parser
import os
import socket
import sys
from datetime import date, datetime, timedelta

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from telegram import Update
from telegram.error import NetworkError as _TgNetworkError, TimedOut as _TgTimedOut

# Lỗi MẠNG giữa máy và server Telegram (wifi chập chờn, máy ngủ dậy, VPN...):
# KHÔNG phải lỗi code → chỉ ghi 1 dòng cảnh báo, không in cả trang traceback.
_TG_NET_ERRORS = (_TgNetworkError, _TgTimedOut)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config_loader import ConfigError, load_config
from log_setup import get_logger
from audit_log import audit
import daily_store
import notes_store
import orchestrator
import pipeline
import state as state_mod
import validator
import excel_writer
import ai_client
import compose_email
import note_action  # edit_timesheet đã thay bằng note_action
import leave_balance
from ai_client import AIError
from excel_writer import ExcelWriterError
import mailer
from mailer import MailerError
from orchestrator import OrchestratorError
from sg_holidays import HolidayError

# Các lỗi NGHIỆP VỤ đã biết trước — mọi lớp này tự mang thông báo
# tiếng Việt rõ ràng, hành động được (vd "Thiếu template, copy vào
# thư mục template trước"). Gặp lỗi loại này, HIỂN THỊ THẲNG str(e)
# cho người dùng đọc ngay trên Telegram — không bắt người dùng phải mò log
# mới biết chuyện gì. Chỉ lỗi NGOÀI danh sách này (bug thật sự chưa
# lường trước) mới cần xem log để debug.
KNOWN_ERRORS = (ExcelWriterError, MailerError, AIError,
               OrchestratorError, HolidayError)

log = get_logger("bot")

SINGLE_INSTANCE_PORT = 47391

# Các câu xác nhận CHỐT GỬI (so khớp nguyên câu sau khi bỏ dấu câu)
CONFIRM_PHRASES = {
    "ok", "oke", "okay", "okey", "yes", "duyệt", "chốt", "send",
    "gởi đi", "gửi đi", "ok gởi", "ok gửi", "ok gởi đi", "ok gửi đi",
}
UNHOLD_PHRASES = {"bỏ khoan", "hết khoan", "unhold", "/unhold"}
# FORCE SEND: không cần cú pháp cứng — AI detect ý định từ ngôn ngữ tự nhiên.
# Một số keyword làm shortcut (bắt ngay không cần AI):
# Lệnh soạn bản nháp sớm — bắt TRƯỚC khi lưu notes
# Xóa file preview bằng ngôn ngữ tự nhiên → tương đương /deletedraft
DELETE_PREVIEW_PHRASES = {
    "xóa excel preview", "xoá excel preview", "xóa preview",
    "xoá preview", "xóa file preview", "xoá file preview",
    "xóa bản nháp", "xoá bản nháp", "xóa nháp", "xoá nháp",
    "xóa excel nháp", "xoá excel nháp", "dọn preview", "dọn nháp",
}

EARLY_SEND_PHRASES = {
    # Tầng 1: hardcode các phrase phổ biến
    "gởi timesheet tới hôm nay", "gửi timesheet tới hôm nay",
    "gởi timesheet hôm nay", "gửi timesheet hôm nay",
    "chốt timesheet hôm nay", "chốt hôm nay",
    "gởi sớm", "gửi sớm",
    # Thêm các variant hay dùng
    "gởi mail timesheet", "gửi mail timesheet",
    "gởi mail sếp", "gửi mail sếp",
    "gởi timesheet", "gửi timesheet",
    "gởi mail đi", "gửi mail đi",
    "gởi mail timesheet đi", "gửi mail timesheet đi",
    "thứ sáu rồi gởi", "thứ sáu rồi gửi",
    "gởi báo cáo", "gửi báo cáo",
}

FORCE_SEND_PHRASES = {
    "cứ gởi đi", "cứ gửi đi", "gởi bằng mọi giá", "gửi bằng mọi giá",
    "bỏ qua lỗi gởi", "bỏ qua lỗi gửi", "force send", "forcesend",
    "gởi dù lỗi", "gửi dù lỗi", "gởi thôi", "gửi thôi",
    "kệ đi gởi", "kệ đi gửi", "cứ gởi", "cứ gửi",
    "vẫn gởi đi", "vẫn gửi đi", "gởi đi", "gửi đi",
    "vẫn gởi", "vẫn gửi",
}
FORCE_SEND_CONFIRM = "YES"

# Prompt detect ý định force send từ câu tự nhiên
# Dùng khi: có pending validation errors VÀ người dùng nhắn gì đó liên quan đến gởi
_FORCE_SEND_DETECT_PROMPT = """người dùng đang có validation errors chưa giải quyết.
người dùng nhắn: "{text}"

người dùng có đang muốn GỞI NGAY dù còn lỗi không? (bypass validation)
Trả lời JSON: {{"want_force_send": true/false}}
true = người dùng muốn gởi dù còn lỗi (các kiểu nói như: cứ gởi, kệ gởi đi,
       gởi thôi, bỏ qua đi, gởi bằng mọi giá, chấp nhận lỗi gởi đi,
       gởi luôn, thôi gởi đi, cứ gởi thôi, ...)
false = người dùng muốn sửa lỗi / không liên quan đến gởi"""

_RESEND_FORCE_EXTRA = {"vẫn gởi", "vẫn gửi", "vẫn gởi lại", "vẫn gửi lại",
                       "gởi luôn", "gửi luôn", "vẫn gởi đi", "vẫn gửi đi"}
_RESEND_FORCE_PHRASES = FORCE_SEND_PHRASES | _RESEND_FORCE_EXTRA
RESEND_PHRASES = {"gởi lại", "gửi lại", "gởi lại đi", "gửi lại đi",
                  "gởi lại cho sếp", "gửi lại cho sếp"}

RESET_NOTES_CMDS    = {"/reset-notes", "/resetnotes"}
RESET_NOTES_CONFIRM = "YES"
CLEAR_NOTES_CMDS    = {"/clearnotes"}  # Telegram không hỗ trợ gạch ngang trong command
CLEAR_NOTES_CONFIRM = "YES"
RESET_STATUS_CMDS   = {"/reset-status", "/resetstatus"}
# Thoát khỏi luồng soạn email / sửa timesheet đang chờ
CANCEL_COMPOSE_PHRASES = {
    "hủy", "huỷ", "cancel", "thôi", "bỏ", "khỏi gửi", "khỏi gởi",
    "hủy email", "huỷ email", "thôi không gửi", "thôi không gởi",
    "dừng", "stop", "hủy soạn", "huỷ soạn", "bỏ qua",
    "hủy gửi mail", "huỷ gửi mail", "reset mail", "reset email",
}

config = None
_instance_lock = None


def acquire_single_instance_lock() -> bool:
    global _instance_lock
    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _instance_lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        return True
    except OSError as e:
        log.debug("Không bind port %d (%s) — đã có instance khác.", SINGLE_INSTANCE_PORT, e)
        return False


def is_allowed(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    chat_id = update.effective_chat.id
    if chat_id == config.telegram_allowed_chat_id:
        return True
    audit("REJECT_STRANGER", f"chat_id={chat_id}")
    log.warning("Từ chối người lạ chat_id=%s", chat_id)
    return False


def _sent_at_local(update: Update) -> datetime:
    """Thời điểm người dùng GỬI tin, đổi sang giờ máy. Telegram gắn sẵn
    field date (UTC) vào mọi tin nhắn — nhờ vậy tin nhắn gửi lúc bot
    đang ngủ vẫn được ghi ĐÚNG NGÀY GỬI, không phải ngày bot bật."""
    sent = update.effective_message.date
    return sent.astimezone().replace(tzinfo=None) if sent else datetime.now()


async def _reply_long(update: Update, text: str):
    """Gửi tin nhắn có thể DÀI, tự cắt theo giới hạn Telegram (~4096
    ký tự/tin). Danh sách câu hỏi khi quét bù nhiều tuần, hoặc khi
    nhiều ngày cùng lỗi, có thể vượt giới hạn -> Telegram từ chối cả
    tin, người dùng KHÔNG NHẬN ĐƯỢC GÌ và tưởng bot chết."""
    for part in orchestrator.chunk_text(text):
        await update.effective_message.reply_text(part)


def _normalize(text: str) -> str:
    """Hạ chữ thường + bỏ dấu câu rìa để so khớp câu lệnh."""
    return text.lower().strip().strip(".,!?~…" + '"').strip()


# ---------------------------------------------------------------------
# Trả kết quả prepare/edit/finalize về cho người dùng
# ---------------------------------------------------------------------

async def _reply_result(update: Update, result: dict):
    status = result.get("status")
    if status == "already_sent":
        await update.effective_message.reply_text(
            f"Kỳ thứ 6 {result['send_day']} gửi rồi nha bro, khỏi lo.")
        return
    if status == "need_info":
        questions = "\n".join(f"• {q}" for q in result["questions"])
        await _reply_long(update,
            "Còn thiếu/vướng mấy chỗ này nè bro:\n" + questions
            + "\n\nBro điền bổ sung (nhắn như ghi chú bình thường). Điền xong thì "
            "gõ /weeklyrun (hoặc nhắn \"gởi timesheet tới hôm nay\") để mình "
            "soạn bản nháp.")
        return
    if status == "ready":
        for part in orchestrator.chunk_text(result["preview"]):
            await update.effective_message.reply_text(part)
        for path in result.get("files") or []:
            with open(path, "rb") as f:
                await update.effective_message.reply_document(
                    document=f, filename=path.name)
        hold_note = ("\n(Đang KHOAN GỞI theo lệnh bro — ok thì mình "
                     "mới gửi.)" if result.get("hold") else "")
        await update.effective_message.reply_text(
            'Ưng thì nhắn "ok" là mình gửi sếp; muốn sửa thì nói tự '
            'nhiên (vd: "thứ 5 đổi thành nghỉ phép").' + hold_note)
        return
    if status == "sent":
        from config_loader import load_config as _lc
        _cfg = _lc()
        await _reply_long(update,
            "📤 ĐÃ GỬI — server mail đã NHẬN (chưa phải chắc chắn sếp nhận)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"From: {result.get('sender') or '?'}\n"
            f"Tới: {_cfg.get('boss_email')}\n"
            f"Bcc: {result.get('bcc') or '(không)'}\n"
            "📎 Đính kèm: " + ", ".join(result["files"]) + "\n"
            f"📁 File trong: thư mục output\n"
            f"✉️ Kiểm tra folder Sent: {result['sent_check']}"
            + (f"\n\n{result['leave_summary']}" if result.get("leave_summary") else ""))
        await _after_weekly_sent(update, result)          # T6–CN: chúc + tự tắt
        return
    await update.effective_message.reply_text(f"Kết quả lạ: {result}")


# ---------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------

HELP_SECTIONS = [
"""🤖 BOT TIMESHEET KN — hướng dẫn (cập nhật 25/9/2026)
Nhắn ghi chú công việc mỗi ngày → bot ghi timesheet → thứ 6 soạn Excel + email cho sếp.

📑 MỤC LỤC
1. Ghi chú hằng ngày (nhắn thường) — ngày, thêm/sửa/xóa
1b. CÚ PHÁP + TỪ KHÓA từng loại task — D/E/F ra sao (prod support, DFU, SDF, NP, WR, nghỉ)
2. Sửa timesheet — /edittimesheet
3. Gửi timesheet cho sếp
4. Email cho sếp (xin nghỉ...) + chọn mail gửi
5. Ngày phép — /leavebal /leavelog /updateleave
6. AI lỗi mạng — /retrynotes & hàng chờ
7. Dữ liệu, backup & dọn dẹp — lệnh xóa
8. Xem nhanh — /status /summary

Mọi thao tác ghi/sửa/gửi đều HIỆN XEM TRƯỚC → 'ok' mới làm, 'hủy' để thôi.""",

"""━━━ 1. GHI CHÚ HẰNG NGÀY (nhắn thường) ━━━
(cách viết TỪNG LOẠI task + cột D/E/F → xem mục 1b ngay sau)
• thứ 5 làm THÊM SDF 2 tiếng → thêm task, GIỮ task cũ, chia lại giờ
• thứ 5 CHỈ làm Coding thôi / ĐỔI LẠI thứ 5 nghỉ phép → ghi đè cả ngày
• nguyên tuần này nghỉ phép · thứ 2 tới thứ 4 làm SDF ABC → cụm ngày, xác nhận 1 lần
• tuần này nghỉ phép · hết tuần trước làm SDF · từ thứ 4 tới hết tuần nghỉ
• cả tháng này / nguyên tháng trước / hết tháng 10 → mọi ngày T2–T6 của tháng
• 15/9 tới 18/9 nghỉ phép · 2 ngày đầu tiên của tháng nghỉ phép
  (tuần/tháng suy ra như vậy LUÔN hiện danh sách ngày, 'ok' mới ghi)
  ⚠️ "thứ 3 tuần này ..." chỉ là 1 ngày thứ 3 — KHÔNG bao giờ thành cả tuần
• thứ 5 làm giống thứ 2 · nguyên tuần này giống thứ 6 tuần trước
• xóa ngày 22/9 → luôn hỏi lại trước khi xóa
• Không nói giờ → chia đều 8h/ngày

Bot hiểu SAI hành động? nhắn: "không phải, thay thế các ngày này thành nghỉ phép" → bot duyệt lại từ đầu.
⛔ Ghi chú thường KHÔNG sửa ngày đã gửi sếp → dùng /edittimesheet.""",

"""━━━ 1b. CÚ PHÁP THEO LOẠI TASK (1/2) ━━━
Chung: <ngày> + <từ khóa task> + <ticket / mô tả>. Mã ticket tự viết HOA, giữ
"Part B"; chữ mô tả GIỮ NGUYÊN. D=Project · E=Task · F=Description.

▶ PRODUCTION SUPPORT → E LUÔN là Issue Investigation, D = Production Support
  Từ khóa: prod issue · prod check · prod fix · production issue ·
  production issue check · production check · production support check
  Cú pháp: <ngày> <từ khóa> cho <Ticket# số - mô tả>[, Ticket# số - mô tả]
  • hôm nay prod issue cho Ticket# 02238471 - to check client receives premium
    notice, Ticket# 479829 - to check policy softlock
    → D: Production Support · E: Issue Investigation
    · F: Ticket# 02238471 - to check client…, Ticket# 479829 - to check policy softlock
  ⚠️ "prod fix CODE" / "prod issue CODE" là SDF (không phải Issue Investigation).
  "production support" đứng MỘT MÌNH không là từ khóa (DFU/SDF cũng có D này).

▶ DFU — ticket ở cột F
  Từ khóa: dfu · data fix · data patch · patch data · deploy data
  • hôm nay DFU pacsdfum-4799 part b, inc2495
    → D: Production Support · E: DFU · F: PACSDFUM-4799 Part B, INC2495

▶ SDF — có chữ mô tả thì ghi "description là"
  Từ khóa: sdf · prod fix code · prod issue code · production code fix
  • hôm nay SDF description là PACSGASIA-4137 issue 1&2 (UAT support)
    → D: Production Support · E: SDF · F: PACSGASIA-4137 issue 1&2 (UAT support)
  (chữ TRONG mô tả như "production issue" KHÔNG đổi task — task theo đầu câu)

▶ NP (New Product) — ticket PACSNP gom 1 dòng ở cột D, F cố định
  Từ khóa: NP · làm NP  +  việc: code / UT → Coding/UT · assess → Investigation/
  Assessment · UAT → UAT Support
  • hôm nay làm NP assess cho pacsnp-7878, pacsnp-5890
    → D: PACSNP-7878, PACSNP-5890 · E: Investigation/Assessment
    · F: New product day 2 items""",

"""━━━ 1b. CÚ PHÁP THEO LOẠI TASK (2/2) ━━━
▶ DỰ ÁN / WR (Coding/UT, UAT, Assessment cho 1 dự án cụ thể)
  Từ khóa (mốc tên): dự án · project · WR
  Cú pháp: <ngày> WR <TÊN DỰ ÁN>, <việc>, mô tả <MÔ TẢ>
  • hôm nay WR PACSPOSCM-2012 AML screening, coding, mô tả GWIA AML screening
    for all payment except Paynow Fast (PL2702)
    → D: PACSPOSCM-2012 AML screening · E: Coding/UT
    · F: GWIA AML screening for all payment except Paynow Fast (PL2702)
  Cách viết linh hoạt:
  – Mốc tên: dự án / project / WR (tên ghi nguyên văn, có thể có số ticket)
  – Mốc mô tả: mô tả / description / desc — có "là" hay ":" hay không đều được
  – Việc: coding / code / UT / unit test → Coding/UT · UAT → UAT Support ·
    assess / assessment → Investigation/Assessment · không ghi → Coding/UT
  Lưu ý: ngăn các phần bằng DẤU PHẨY → tên dự án đừng có phẩy (có thì ngăn bằng
  "|"); tên trùng chữ "UAT" (vd "UAT tool revamp") KHÔNG làm đổi việc.

▶ NGHỈ — D = E = loại nghỉ, F trống
  Từ khóa: nghỉ phép / off / leave → Annual Leave · nghỉ bệnh / nghỉ ốm / bị bệnh
  → Sick Leave (nhớ gửi MC) · nghỉ bù → Special Leave · nghỉ lễ → Public Holiday
  • hôm nay nghỉ phép → Annual Leave 8h
  • nửa ngày: "sáng nay nghỉ phép" / "hôm nay nghỉ phép nửa ngày" → 4h

▶ NHIỀU TASK TRONG 1 NGÀY — ghi SỐ GIỜ từng phần, ngăn bằng dấu phẩy
  • hôm nay nghỉ phép 4 tiếng, 4 tiếng làm DFU pacsdfum-4482
    → 2 dòng: Annual Leave 4h + DFU 4h (PACSDFUM-4482)
  (phần không ghi giờ → bot chia đều số giờ còn lại cho đủ 8h; chạy được cả
  khi AI lỗi mạng — vẫn xem kỹ bản xem trước rồi mới 'ok')""",

"""━━━ 2. SỬA TIMESHEET — /edittimesheet ━━━
Dùng cho ngày ĐÃ gửi sếp (tuần trước...) lẫn ngày trong tuần này.
  /edittimesheet
  → nhắn: ngày 10/9: nghỉ phép 2 tiếng, 6 tiếng SDF PACSGASIA-7763
  → xem bản sửa → 'ok' (hoặc nói sửa lại, lặp tới khi đúng; 'hủy' để thoát)
Ví dụ khác:
• sửa thứ 2 tới thứ 4 tuần trước nghỉ phép
• nguyên tuần đầu tiên của tháng nghỉ phép
• thứ 4 tuần trước làm giống thứ 2 tuần này
• xóa ngày 16/9
Ngày ĐÃ GỬI → ghi cả Excel + parsed_days → gõ /resend (hoặc nhắn 'gởi lại')
để gửi sếp bản mới
(có xem trước). KHÔNG dùng /sendmail hay /createdraft cho tuần đã gửi.""",

"""━━━ 3. GỬI TIMESHEET CHO SẾP ━━━
Tự động: thứ 6 17:00 bot soạn nháp. Chạy tay: /weeklyrun
Duyệt: 'ok' → bot hiện EMAIL XEM TRƯỚC (From/To/Bcc/Subject/nội dung/D-E-F
từng ngày) → 'ok' LẦN 2 mới gửi · 'hủy' hoặc /resetmailts → KHÔNG gửi.
/manualmail (lúc đang xem trước, cả khi gởi lại) → tự gõ 100% nội dung email,
bot gửi NGUYÊN VĂN, giữ tiêu đề + file đính kèm, không lưu lại ở đâu.
Câu nhắn thường:
• gởi timesheet tới hôm nay → chốt sớm
• khoan gởi / bỏ khoan → tạm giữ, không gửi tự động / cho gửi lại
• cứ gởi đi → gửi dù còn cảnh báo
• /resend (hoặc nhắn 'gởi lại') → gửi lại tháng vừa sửa (có xem trước). Bị chặn → sửa
  rồi /resend lần nữa, hoặc 'vẫn gởi' / /forcesendmail để bỏ qua cảnh báo
Lệnh:
/createdraft · /forcedraft (bỏ qua lỗi) · /checkdraft · /deletedraft
/sendmail · /forcesendmail (gửi dù còn lỗi, kể cả còn tin chờ)
/checkexcel (kiểm file Excel tháng) · /checknotes (kiểm D/E/F)
Sau khi gửi: bot báo số dư phép + tự dọn notes.jsonl (có backup).""",

"""━━━ 4. EMAIL CHO SẾP ━━━
/composemail → nhắn ý bằng tiếng Việt, AI soạn tiếng Anh:
  "xin nghỉ chiều mai" → "tomorrow afternoon, Friday 25/9 (halfday afternoon)"
  (luôn có thứ + ngày dạng 25/9; xem trước có số dư phép)
  'ok' gửi · nói sửa ("thêm as communicated") · 'hủy' hoặc /resetmail → KHÔNG gửi
/composemanual → tự gõ Subject + nội dung

Gửi bằng mail nào (áp cho CẢ timesheet lẫn email nghỉ phép):
• MẶC ĐỊNH: mail công ty ("company_email" trong settings.json), Bcc "bcc_when_company"
• /personalmailon → Gmail cá nhân (Bcc mail công ty) — hỏi 'ok' trước
• /personalmailoff → quay về mail công ty
Gửi LỖI (sai mật khẩu, mạng chặn cổng, SSL, sếp bị từ chối, file quá lớn...)
→ "❌ MAIL CHƯA GỬI ĐƯỢC" + lý do + cách xử lý; email đang chờ được GIỮ →
/personalmailon (hoặc /personalmailoff) → 'ok' → bot hiện lại email → 'ok'.
Bot KHÔNG tự đổi mail. Gửi xong = "📤 ĐÃ GỬI" (server mail đã nhận, bot không dò thêm).""",

"""━━━ 5. NGÀY PHÉP ━━━
• Annual Leave 17 ngày/năm · Sick Leave 14 ngày/năm (cần MC)
  → reset 1/1, phép dư KHÔNG chuyển sang năm sau
  → đổi số: config\\settings.json "annual_leave_per_year", "sick_leave_per_year"
    (báo trước cho năm sau: "leave_entitlement_by_year": {"2027": {"annual": 18}})
• Special Leave: +1 ngày cho MỖI lễ rơi thứ 7 (lịch MOM), dùng trong 3 THÁNG
  kể từ ngày lễ; bot trừ ngày sắp hết hạn trước.
• Tự tính lại từ file Excel đã gửi mỗi lần xem / gửi / gởi lại (không trừ trùng).
  Nghỉ 4 tiếng = 0,5 ngày.

/leavebal — số dư: "đã chốt" (đã gửi) + "dự kiến" (thêm ngày tuần này chưa gửi),
            danh sách ngày bù và hạn dùng
/leavelog — từng ngày đã nghỉ trong năm (✅ đã gửi · 🕓 chưa gửi)
/updateleave — nhập tay số ngày CÒN LẠI HIỆN TẠI; từ đó MỌI thay đổi (kể cả
  sửa ngày CŨ bằng /edittimesheet) đều trừ/cộng vào con số này:
  /updateleave AL 10          phép năm còn 10
  /updateleave SICK 14 SL 0   nghỉ bệnh còn 14, nghỉ bù còn 0
  /updateleave AL 9.5         còn 9 ngày rưỡi
  /updateleave AL 0           hết phép năm
  /updateleave reset          bỏ mốc, để bot tự tính lại
  ⚠️ LẦN ĐẦU dùng bot: đặt số thật — các tháng trước khi có bot không có Excel để đếm.
  Nghỉ bù KHÔNG phải do lễ T7 (vd bù OT): khai /updateleave SL <n> → bot chấp nhận
  theo số dư đó; vượt số dư → 'gởi lại' báo, nhắn 'vẫn gởi' nếu muốn gửi luôn.
Nhắc tự động: ngày bù còn ≤14 ngày hết hạn (ở /leavebal, /status, sau khi gửi);
xin nghỉ quá số dư (trong xem trước /composemail); ghi Sick Leave → nhớ gửi MC.""",

"""━━━ 6. AI LỖI MẠNG — /retrynotes & HÀNG CHỜ ━━━
Khi AI không kết nối được, bot TỰ bóc câu bằng luật có sẵn (rule) → LUÔN hiện
xem trước, 'ok' mới ghi / sửa / xóa. Luật xóa được CẢ NGÀY ("xóa ngày 22/9",
"xóa nguyên tuần"); xóa 1 task hay câu "giống ngày khác" thì chờ AI.
Nếu luật cũng không hiểu câu đó → tin được đưa vào HÀNG CHỜ, CHƯA ghi vào timesheet.

HÀNG CHỜ là gì?
• Danh sách tin CHƯA xử lý được, lưu trong data\\state.json (mục "pending_notes").
• Còn tin chờ → bot CHẶN tạo nháp & gửi timesheet, để không gửi sếp bản THIẾU
  (/forcesendmail vẫn gửi được nếu bro chấp nhận).
• /status luôn báo số tin đang chờ.

Khi nào dùng: khi mạng/AI ổn lại (vài phút sau), hoặc khi /status báo có tin chờ.
/retrynotes       → xử lý lại tin đầu tiên (AI vẫn lỗi → tin quay lại hàng chờ)
/retrynotes xem   → xem danh sách tin đang chờ
/retrynotes bỏ    → bỏ tin đầu (khi bro đã tự gõ lại câu khác)

Hàng chờ KHÁC notes.jsonl thế nào?
• notes.jsonl = NHẬT KÝ mọi tin bro từng nhắn, chỉ để tra lại; bot KHÔNG dùng nó
  để quyết định ghi gì. Tự làm trống sau mỗi lần gửi timesheet.
• Hàng chờ = chỉ những tin CHƯA vào timesheet; KHÔNG bị dọn cho tới khi
  bro xử lý (/retrynotes) hoặc bỏ (/retrynotes bỏ).""",

"""━━━ 7. DỮ LIỆU, BACKUP & DỌN DẸP (thư mục timesheet) ━━━
data\\parsed_days.json — QUAN TRỌNG NHẤT: nội dung timesheet từng ngày, nguồn tạo Excel.
  • KHÔNG xóa, KHÔNG sửa tay. Ngày cũ hơn 120 ngày tự bỏ (vẫn còn trong Excel).
  • Nếu file hỏng: bot cất bản hỏng vào data\\backup\\corrupt\\ và báo ở /status.
    Khôi phục: chép bản mới nhất trong data\\backup\\parsed_days_daily\\ về
    data\\parsed_days.json rồi khởi động lại bot.
data\\notes.jsonl — nhật ký tin nhắn. Sau mỗi lần GỬI thành công: backup rồi làm trống.
TẤT CẢ BACKUP dữ liệu nằm trong data\\backup\\ (tự dọn theo hạn):
  notes\\               notes.jsonl.bak_*         giữ 30 ngày (mỗi tuần ~1 file)
  parsed_days_daily\\   parsed_days_YYYYMMDD.json  chụp mỗi ngày, giữ 60 ngày
  parsed_days\\         parsed_days.json.bak_*     (do /resetnotes) giữ 90 ngày
  corrupt\\             parsed_days.json.corrupt_* giữ 90 ngày
  (backup\\ ngoài thư mục timesheet: bản sao Excel trước khi ghi, giữ 90 ngày)
output\\LiveReport_YYYY-MM.xlsx — bản đã gửi sếp, giữ vĩnh viễn (nguồn tính phép).
Dọn dẹp tự chạy 1 lần/ngày khi bot khởi động.

LỆNH XÓA (từ nhẹ tới mạnh):
/resetstatus — gỡ trạng thái kẹt (nháp/câu hỏi treo), KHÔNG xóa dữ liệu
/deletedraft — xóa bản nháp đang chờ gửi
/clearnotes  — làm trống notes.jsonl (có backup), GIỮ parsed_days. Hiếm khi cần.
/resetnotes  — xóa CẢ notes lẫn parsed_days (có backup). CHỈ khi muốn làm lại
               từ đầu — KHÔNG khuyến khích.""",

"""━━━ 8. XEM NHANH ━━━
/status — tình trạng timesheet (đang nhập / có nháp / chờ gửi / đã gửi...),
          từng ngày T2–T6 có hay thiếu, điền tới ngày nào, tin chờ,
          Excel, ngày phép Annual/Sick/Special, mail đang dùng, AI, backup
/summary — toàn bộ công việc theo ngày · /summaryweek — tuần này
/help hoặc /start — xem lại hướng dẫn này""",
]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start, /help — hướng dẫn đầy đủ, gửi TỪNG PHẦN (không cắt giữa mục)."""
    if not is_allowed(update):
        return
    audit("CMD", update.effective_message.text)
    for part in HELP_SECTIONS:
        await _reply_long(update, part)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — tổng quan: tình trạng timesheet, từng ngày trong kỳ, ngày
    phép, mail, AI, backup. Nội dung dựng ở status_report.py."""
    if not is_allowed(update):
        return
    import status_report
    text = await asyncio.to_thread(status_report.build_status, config)
    await _reply_long(update, text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    text = update.effective_message.text.strip()
    if not text:
        return
    normalized = _normalize(text)
    async with state_mod.async_state_lock() as got_lock:
        if not got_lock:
            log.warning("Không lấy được khóa state — báo bận, bỏ qua tin này.")
            audit("BUSY_SKIPPED", text[:80])
            await update.effective_message.reply_text(
                "Mình đang bận xử lý timesheet (job thứ 6 đang chạy) nên "
                "chưa nhận tin này được. Bro nhắn lại sau khoảng 1 phút "
                "giúp mình nha — tin nhắn chưa được ghi đâu.")
            return
        state = state_mod.load_state()
        draft_pending = state.get("draft") is not None
        awaiting = bool((state.get("conversation") or {}).get("awaiting"))
        _is_manual = (state.get("conversation") or {}).get("awaiting") == "manual_mail_body"
        log.info("Tin nhắn (%d ký tự, draft=%s, awaiting=%s): %s",
                 len(text), draft_pending, awaiting,
                 "(nội dung email tự gõ — KHÔNG ghi log)" if _is_manual else text[:80])

        try:
            # ===== COMPOSE EMAIL (module phụ, tách biệt timesheet) =====
            conv = state.get("conversation") or {}
            awaiting_val = conv.get("awaiting")

            # THOÁT khỏi luồng soạn email/sửa timesheet khi:
            # - gõ bất kỳ lệnh / (vd /summary, /resetmail)
            # - nhắn từ khóa hủy
            # → clear conversation, cho tin nhắn xử lý bình thường
            _compose_states = {"compose_ai_request", "compose_manual_input",
                               "compose_confirm", "past_edit_request",
                               "past_edit_confirm", "ts_mail_confirm",
                               "personal_mail_confirm", "resend_confirm",
                               "resend_need_info",
                               "update_leave_input", "update_leave_confirm"}
            if awaiting_val in _compose_states:
                is_command = text.strip().startswith("/")
                is_cancel = normalized in CANCEL_COMPOSE_PHRASES
                if is_command or is_cancel:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    audit("COMPOSE_CANCELLED", f"by {'command' if is_command else 'cancel'}")
                    if is_cancel:
                        await update.effective_message.reply_text(
                            "Đã hủy. Trở lại bình thường — nhắn gì cũng được.")
                        return
                    # là lệnh / → clear rồi để lệnh tự chạy (không return,
                    # nhưng conv đã clear nên các handler dưới xử lý đúng)
                    conv = {}
                    awaiting_val = None

            # A) Đang chờ người dùng NHẬP YÊU CẦU (AI mode) — bước 1
            if awaiting_val == "compose_ai_request":
                await update.effective_message.reply_text(
                    "Đang soạn email…")
                try:
                    email = await asyncio.to_thread(
                        compose_email.compose_with_ai, text, config)
                except ai_client.AIError as e:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        f"Soạn email lỗi ({e}). Thử lại /composemail nhé.")
                    return
                state["conversation"] = {
                    "awaiting": "compose_confirm",
                    "email": email}
                state_mod.save_state(state)
                await _reply_long(update,
                    compose_email.format_preview(email, config))
                return

            # B) Đang chờ người dùng NHẬP TAY subject+body (manual mode) — bước 1
            if awaiting_val == "compose_manual_input":
                try:
                    email = compose_email.parse_manual_input(text)
                except ValueError as e:
                    await update.effective_message.reply_text(
                        f"{e}\n\nNhập lại giúp mình, hoặc /composemanual để bắt đầu lại.")
                    return
                state["conversation"] = {
                    "awaiting": "compose_confirm",
                    "email": email}
                state_mod.save_state(state)
                await _reply_long(update,
                    compose_email.format_preview(email, config))
                return

            # D) SỬA TIMESHEET ĐÃ GỬI — bước 1: nhập nội dung sửa
            if awaiting_val == "past_edit_request":
                await update.effective_message.reply_text(
                    "Đang bóc tách nội dung sửa…")
                try:
                    acts, not_act = await asyncio.to_thread(
                        note_action.parse_actions, text, config)
                except ai_client.AIError as e:
                    await _fallback_rule_parser(update, state, text, e,
                                                source="edit")
                    return
                if not_act or not acts:
                    await update.effective_message.reply_text(
                        "Chưa rõ bro muốn sửa gì. Nhắn dạng 'ngày DD/MM: task', "
                        "hoặc nhắn 'hủy' để thoát.")
                    return
                pd = daily_store.load_all()
                acts = note_action.validate_actions(acts, pd, config)
                # Lưu actions vào state (serialize)
                state["conversation"] = {
                    "awaiting": "past_edit_confirm",
                    "note_actions": _serialize_actions(acts)}
                state_mod.save_state(state)
                await _reply_long(update, note_action.format_preview(acts))
                return

            # E) SỬA TIMESHEET — bước 2: xác nhận / sửa lại (note_action)
            if awaiting_val == "past_edit_confirm":
                if normalized in CONFIRM_PHRASES:
                    acts = _deserialize_actions(conv.get("note_actions", []))
                    # Chặn nếu mọi action đều error
                    if all(a.error for a in acts):
                        state["conversation"] = None
                        state_mod.save_state(state)
                        await _reply_long(update,
                            "Không ghi được — còn lỗi:\n"
                            + "\n".join(f"• {a.error}" for a in acts if a.error))
                        return
                    await update.effective_message.reply_text("Đang ghi bản sửa…")
                    try:
                        res = await asyncio.to_thread(
                            note_action.persist_actions, acts, config,
                            state_mod.load_state(), True)  # also_excel_if_sent
                    except Exception as e:  # noqa: BLE001
                        log.exception("note_action persist lỗi")
                        state["conversation"] = None
                        state_mod.save_state(state)
                        await update.effective_message.reply_text(
                            f"Ghi bản sửa lỗi ({type(e).__name__}: {e}).")
                        return
                    excel_months = res.get("excel_months", [])
                    state["conversation"] = None
                    if res.get("draft_invalidated"):   # bản nháp cũ đã HỦY (02-Oct) —
                        state["draft"] = None          # không lưu đè nó trở lại
                    if excel_months:  # có ngày đã gửi → nhớ để "gởi lại"
                        state["last_edited_months"] = excel_months
                    state_mod.save_state(state)
                    audit("EDIT_TIMESHEET_APPLIED",
                          f"touched={res.get('touched')}, "
                          f"excel_months={excel_months}")

                    # Thông báo — dựa vào NGÀY NÀO ĐÃ GỬI (sửa 24-Sep; trước dựa
                    # vào "có file Excel không" → Excel lỗi bị báo nhầm "CHƯA gửi")
                    sent = set(res.get("sent_days") or [])
                    rolled = set(res.get("rolled_back") or [])
                    def _day_lines(pred):
                        out = []
                        for d, ents in sorted(res.get("written_days", []), key=lambda x: x[0]):
                            if not pred(d.isoformat()):
                                continue
                            if ents is None:
                                out.append(f"  • {note_action._dmy(d)}: đã xóa")
                            else:
                                out.append(f"  • {note_action._dmy(d)}: " + ", ".join(
                                    f"{x.get('task')} {float(x.get('hours') or 0):g}h" for x in ents))
                        return out
                    err = res.get("excel_error")
                    if err:
                        audit("EDIT_TIMESHEET_EXCEL_FAIL", f"{err} | hoàn tác {sorted(rolled)}")
                        parts = ["⚠️ CHƯA SỬA ĐƯỢC NGÀY ĐÃ GỬI SẾP",
                                 "━━━━━━━━━━━━━━━━━━",
                                 "Ngày đã gửi: " + ", ".join(
                                     note_action._dmy(date.fromisoformat(i)) for i in sorted(rolled)),
                                 "→ KHÔNG đổi gì: parsed_days đã HOÀN TÁC, Excel vẫn như cũ.",
                                 f"Lý do: {err}",
                                 "Cách làm: đóng file Excel (nếu đang mở) rồi /edittimesheet làm lại."]
                        other = _day_lines(lambda i: i not in rolled)
                        if other:
                            parts += ["━━━━━━━━━━━━━━━━━━",
                                      "Ngày CHƯA gửi trong câu vẫn ghi bình thường:", *other]
                        await _reply_long(update, "\n".join(parts))
                        return
                    parts = ["✅ ĐÃ CẬP NHẬT TIMESHEET THÀNH CÔNG!",
                             "━━━━━━━━━━━━━━━━━━"]
                    _mc = note_action.mc_reminder(res)
                    sent_lines = _day_lines(lambda i: i in sent)
                    unsent_lines = _day_lines(lambda i: i not in sent)
                    if sent_lines:
                        parts += ["📌 Ngày ĐÃ GỬI sếp — đã ghi CẢ Excel lẫn parsed_days:",
                                  *sent_lines,
                                  *[f"  📄 output\\{f}" for f in res.get("excel_files", [])],
                                  "💾 File Excel cũ backup trong thư mục backup"]
                    if unsent_lines:
                        parts += ["📝 Ngày CHƯA gửi — đã ghi parsed_days (vào Excel khi /weeklyrun):",
                                  *unsent_lines]
                    if _mc:
                        parts.append(_mc)
                    if res.get("draft_invalidated"):
                        parts += ["━━━━━━━━━━━━━━━━━━", "⚠️ Bản nháp timesheet đang chờ gửi có chứa ngày bro vừa sửa → bản nháp CŨ đã được HỦY (để không gửi nhầm bản chưa sửa). Gõ /createdraft để soạn lại bản nháp mới (file Excel xem trước nằm trong data\\preview), rồi 'ok' → 'ok' để gửi."]
                    if sent_lines:
                        parts += ["━━━━━━━━━━━━━━━━━━",
                                  "📤 MUỐN GỬI LẠI CHO SẾP: gõ /resend (hoặc nhắn 'gởi lại') → xem trước rồi mới gửi",
                                  "  (KHÔNG dùng /sendmail hay /createdraft cho tuần đã gửi)"]
                    await _reply_long(update, "\n".join(parts))
                    return
                elif normalized in CANCEL_COMPOSE_PHRASES:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Đã hủy sửa timesheet. Không đụng gì vào dữ liệu.")
                    return
                else:
                    # Yêu cầu SỬA LẠI → DUYỆT ACTION TỪ ĐẦU với câu đính chính.
                    # Kèm CONTEXT ngày của bản trước để AI hiểu "các ngày này",
                    # "sửa lại action" khi câu đính chính thiếu ngày cụ thể.
                    await update.effective_message.reply_text("Đang duyệt lại…")
                    prev_acts = _deserialize_actions(conv.get("note_actions", []))
                    prev_days = sorted({a.day.isoformat() for a in prev_acts
                                        if a.day})
                    try:
                        acts, not_act = await asyncio.to_thread(
                            note_action.parse_actions, text, config,
                            prev_days)   # truyền context ngày trước
                    except ai_client.AIError as e:
                        # AI lỗi ở bước SỬA LẠI → cũng đi luật dự phòng (trước
                        # 24-Sep: in thẳng lỗi kỹ thuật "rule_parser_mode: ...")
                        log.warning("Sửa lại: AI lỗi (%s) — thử rule_parser.", e)
                        r_acts, why = note_action.actions_from_rule_parser(
                            text, date.today())
                        if not r_acts:
                            await update.effective_message.reply_text(
                                "🔌 AI đang lỗi mạng, và luật dự phòng không hiểu câu "
                                f"sửa lại này ({why}). Bản xem trước lúc nãy VẪN GIỮ: "
                                "nhắn 'ok' để ghi bản đó, nói lại rõ 'ngày DD/MM: task', "
                                "hoặc nhắn 'hủy' để thoát.")
                            return
                        acts, not_act = r_acts, False
                    if not_act or not acts:
                        await update.effective_message.reply_text(
                            "Chưa rõ yêu cầu sửa. Nói rõ hơn (vd 'thay thế các "
                            "ngày này thành nghỉ phép'), hoặc 'ok'/'hủy'.")
                        return
                    pd = daily_store.load_all()
                    acts = note_action.validate_actions(acts, pd, config)
                    _src = conv.get("source", "edit")
                    if _src == "nl":
                        _sent = _sent_days_in_actions(acts, state)
                        if _sent:
                            state["conversation"] = None
                            state_mod.save_state(state)
                            audit("NL_EDIT_BLOCKED_SENT_DAY",
                                  ", ".join(d.isoformat() for d in _sent))
                            await _reply_long(
                                update, _block_sent_days_msg(_sent, state))
                            return
                    state["conversation"] = {
                        "awaiting": "past_edit_confirm",
                        "source": _src,
                        "note_actions": _serialize_actions(acts)}
                    state_mod.save_state(state)
                    await _reply_long(update, note_action.format_preview(acts))
                    return

            # C) Đang chờ người dùng XÁC NHẬN gửi / SỬA email — bước 2
            if awaiting_val == "compose_confirm":
                email = conv.get("email", {})
                if normalized in CONFIRM_PHRASES:
                    # Gửi email
                    await update.effective_message.reply_text("Đang gửi email…")
                    try:
                        result = await asyncio.to_thread(
                            compose_email.send_composed_email, email, config)
                    except MailerError as e:
                        # GIỮ email nháp (không xóa) → đổi mail rồi 'ok'
                        await _reply_long(update, str(e))
                        return
                    except Exception as e:  # noqa: BLE001
                        log.exception("compose_email gửi lỗi")
                        await update.effective_message.reply_text(
                            f"❌ Gửi email lỗi ({type(e).__name__}: {e}) — sếp "
                            "CHƯA nhận. Email nháp vẫn giữ: nhắn 'ok' thử lại, "
                            "/personalmailon để đổi sang Gmail, 'hủy' để bỏ.")
                        return
                    state["conversation"] = None
                    state_mod.save_state(state)
                    audit("COMPOSE_EMAIL_SENT",
                          f"to={result['to']}; subject={result['subject']!r}")
                    await _reply_long(update,
                        compose_email.format_sent_confirmation(result))
                    return
                elif normalized in {"hủy", "huỷ", "cancel", "thôi", "bỏ", "khỏi gửi"}:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Đã hủy soạn email.")
                    return
                else:
                    # Coi là YÊU CẦU SỬA → gọi AI modify (nếu email do AI soạn)
                    await update.effective_message.reply_text("Đang sửa email…")
                    try:
                        new_email = await asyncio.to_thread(
                            compose_email.modify_with_ai, email, text, config)
                    except ai_client.AIError as e:
                        await update.effective_message.reply_text(
                            f"Sửa email lỗi ({e}). Nói lại giúp mình, "
                            "hoặc 'ok' để gửi bản hiện tại, 'hủy' để bỏ.")
                        return
                    state["conversation"] = {
                        "awaiting": "compose_confirm",
                        "email": new_email}
                    state_mod.save_state(state)
                    await _reply_long(update,
                        compose_email.format_preview(new_email, config))
                    return

            # 0-pm) XÁC NHẬN BẬT GỬI BẰNG GMAIL CÁ NHÂN
            if awaiting_val == "personal_mail_confirm":
                state["conversation"] = None
                try:
                    _age = (datetime.now() - datetime.fromisoformat(
                        conv.get("at", ""))).total_seconds()
                except (TypeError, ValueError):
                    _age = 10 ** 9
                if _age > 300:
                    # Hết hạn → bỏ lời hỏi, trả email đang chờ (nếu có) về chỗ cũ
                    if conv.get("resume"):
                        state["conversation"] = conv["resume"]
                        state_mod.save_state(state)
                        await update.effective_message.reply_text(
                            "Lời hỏi đổi sang Gmail đã hết hạn (5 phút) — KHÔNG đổi. "
                            "Email đang chờ vẫn còn: 'ok' để gửi bằng mail hiện tại, "
                            "hoặc /personalmailon lại.")
                        return
                    state_mod.save_state(state)
                    log.info("personal_mail_confirm hết hạn (%.0fs) — bỏ qua.", _age)
                    conv = {}
                    awaiting_val = None
                elif normalized in CONFIRM_PHRASES:
                    state["mail_mode"] = "personal"
                    state_mod.save_state(state)
                    audit("MAIL_MODE", "personal (bật /personalmailon)")
                    await update.effective_message.reply_text(
                        "✅ Đã BẬT: từ giờ gửi bằng GMAIL CÁ NHÂN "
                        f"({config.gmail_address}), Bcc mail công ty.\n"
                        "Áp dụng cho cả email timesheet lẫn email nghỉ phép.\n"
                        "/personalmailoff để quay lại mail công ty.")
                    if conv.get("resume"):
                        await _reshow_pending(update, conv["resume"])
                    return
                else:
                    state["conversation"] = conv.get("resume")
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Không đổi — vẫn gửi bằng MAIL CÔNG TY."
                        + (" Email đang chờ vẫn còn: 'ok' để gửi." if conv.get("resume") else ""))
                    return

            # 0-lv) /updateleave — nhập số / xác nhận
            if awaiting_val == "update_leave_input":
                await _updateleave_preview(update, state, text)
                return
            if awaiting_val == "update_leave_confirm":
                vals = conv.get("values") or {}
                state["conversation"] = None
                if normalized in CONFIRM_PHRASES and vals:
                    leave_balance.apply_update(state, vals, config=config)
                    state_mod.save_state(state)
                    audit("LEAVE_UPDATE", str(vals))
                    r = await asyncio.to_thread(
                        leave_balance.compute_balance, config, state)
                    await _reply_long(update, "✅ Đã lưu.\n\n"
                                      + leave_balance.format_balance(r))
                    return
                state_mod.save_state(state)
                await update.effective_message.reply_text(
                    "Đã hủy, số ngày phép KHÔNG đổi.")
                return

            # 0-rn) 'gởi lại' bị CẢNH BÁO → người dùng chọn 'vẫn gởi' / 'hủy'
            if awaiting_val == "resend_need_info":
                months_to_send = conv.get("months") or []
                if normalized in _RESEND_FORCE_PHRASES:
                    prev = await asyncio.to_thread(
                        orchestrator.prepare_resend_preview, months_to_send,
                        config, state, True)
                    if prev.get("status") != "review":
                        state["conversation"] = None
                        state_mod.save_state(state)
                        await _reply_long(update, str(prev.get("questions") or prev))
                        return
                    state["conversation"] = {"awaiting": "resend_confirm",
                                             "months": months_to_send, "force": True}
                    state_mod.save_state(state)
                    await _reply_long(update, "(đã BỎ QUA cảnh báo theo ý bro)\n\n"
                                      + prev["preview"])
                    return
                state["conversation"] = None
                state_mod.save_state(state)
                if normalized not in CANCEL_COMPOSE_PHRASES:
                    await update.effective_message.reply_text(
                        "Chưa gởi lại. Muốn sửa ngày đó: /edittimesheet rồi nhắn "
                        "'gởi lại'. Muốn gửi luôn: 'gởi lại' → 'vẫn gởi'.")
                else:
                    await update.effective_message.reply_text("Đã hủy gởi lại.")
                return

            # 0-mm) /manualmail — bro đang GÕ nội dung email
            if awaiting_val == "manual_mail_body":
                back = dict(conv.get("back") or {})
                if normalized in CANCEL_COMPOSE_PHRASES:
                    _MANUAL_BODY.clear()
                    back.pop("manual", None)
                    await update.effective_message.reply_text(
                        "Đã bỏ nội dung tự gõ — dùng lại email TỰ ĐỘNG:")
                    await _reshow_pending(update, back)
                    return
                body = update.effective_message.text.rstrip()
                _MANUAL_BODY["body"] = body          # CHỈ trong bộ nhớ, không lưu file
                audit("MANUAL_MAIL", f"{len(body)} ký tự")
                back["manual"] = True
                await _reshow_pending(update, back)
                return

            # 0-rs) XÁC NHẬN GỞI LẠI (sau khi xem preview gởi lại)
            if awaiting_val == "resend_confirm":
                months_to_send = conv.get("months") or []
                state["conversation"] = None
                state_mod.save_state(state)
                if normalized in CONFIRM_PHRASES and months_to_send:
                    manual = _manual_body_or_warn(conv)
                    if manual is False:
                        state["conversation"] = conv
                        state_mod.save_state(state)
                        await update.effective_message.reply_text(_MANUAL_LOST_MSG)
                        return
                    await update.effective_message.reply_text(
                        f"Ok, đang gởi lại cho sếp (tháng {', '.join(months_to_send)})…"
                        + (" (nội dung email bro TỰ GÕ)" if manual else ""))
                    _force = bool(conv.get("force"))
                    try:
                        result = await asyncio.to_thread(
                            orchestrator.resend_months, months_to_send, config,
                            state_mod.load_state(), _force, manual)
                    except MailerError as e:
                        st2 = state_mod.load_state()
                        st2["conversation"] = {"awaiting": "resend_confirm",
                                               "months": months_to_send,
                                               "force": _force, "manual": bool(manual)}
                        state_mod.save_state(st2)
                        await _reply_long(update, str(e))
                        return
                    if result.get("status") == "sent":
                        _MANUAL_BODY.clear()
                        st2 = state_mod.load_state()
                        st2["last_edited_months"] = None
                        state_mod.save_state(st2)
                    await _reply_result(update, result)
                    return
                await update.effective_message.reply_text(
                    "✅ Đã hủy gởi lại. KHÔNG có mail nào được gửi. Sửa tiếp "
                    "bằng /edittimesheet rồi nhắn 'gởi lại' khi xong.")
                return

            # 0-ts) XÁC NHẬN GỬI EMAIL TIMESHEET (sau khi xem preview)
            if awaiting_val == "ts_mail_confirm":
                if normalized in CONFIRM_PHRASES:
                    manual = _manual_body_or_warn(conv)
                    if manual is False:
                        await update.effective_message.reply_text(_MANUAL_LOST_MSG)
                        return
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Ok, đang ghi file + gửi mail cho sếp…"
                        + (" (nội dung email bro TỰ GÕ)" if manual else ""))
                    try:
                        result = await asyncio.to_thread(
                            orchestrator.finalize_and_send, config, state, False, manual)
                    except MailerError as e:
                        # GIỮ email đang chờ (kể cả nội dung tự gõ) → đổi mail rồi 'ok'
                        st2 = state_mod.load_state()
                        st2["conversation"] = {"awaiting": "ts_mail_confirm", "manual": bool(manual)}
                        state_mod.save_state(st2)
                        await _reply_long(update, str(e))
                        return
                    if result.get("status") == "sent":
                        _MANUAL_BODY.clear()
                    await _reply_result(update, result)
                    return
                elif (normalized in CANCEL_COMPOSE_PHRASES
                      or text.strip().startswith("/")):
                    state["conversation"] = None
                    state_mod.save_state(state)
                    if not text.strip().startswith("/"):
                        await update.effective_message.reply_text(
                            "✅ Đã hủy gửi email timesheet. KHÔNG có mail nào "
                            "được gửi. Bản nháp vẫn còn — sửa rồi /weeklyrun "
                            "lại, hoặc /checkdraft xem lại.")
                        return
                    # là lệnh / → clear rồi cho lệnh chạy
                    conv = {}
                    awaiting_val = None
                else:
                    await update.effective_message.reply_text(
                        "Nhắn 'ok' để GỬI cho sếp, hoặc 'hủy' / /resetmailts "
                        "để hủy (sửa lại timesheet).")
                    return

            # 0a) XÁC NHẬN CLEAR NOTES (chỉ xóa notes, giữ parsed_days)
            if (state.get("conversation", {}) or {}).get("awaiting") == "clear_notes_confirm":
                if text.strip().upper() == CLEAR_NOTES_CONFIRM:
                    try:
                        result = notes_store.clear_notes_only()
                        state["conversation"] = None
                        state_mod.save_state(state)
                        audit("NOTES_CLEAR_KEEP_PARSED",
                              f"xóa {result['line_count']} dòng, "
                              f"backup={result.get('backup')}")
                        n_parsed = len(daily_store.load_all())
                        await update.effective_message.reply_text(
                            f"✅ Đã xóa {result['line_count']} dòng ghi chú thô "
                            f"(notes.jsonl).\n"
                            f"📁 Backup: {result.get('backup') or '(không có)'}\n\n"
                            f"parsed_days.json GIỮ NGUYÊN ({n_parsed} ngày) — "
                            f"/createdraft, /weeklyrun, /summary vẫn chạy bình thường.\n"
                            f"Ghi chú mới từ giờ sẽ sạch, không còn dấu vết cũ.")
                    except Exception as e:
                        log.exception("/clearnotes lỗi")
                        state["conversation"] = None
                        state_mod.save_state(state)
                        await update.effective_message.reply_text(
                            f"Lỗi xóa notes: {type(e).__name__}: {e}")
                else:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Đã hủy. notes.jsonl vẫn nguyên.")
                return

            # 0) XÁC NHẬN RESET NOTES — PHẢI trước CONFIRM_PHRASES
            #    "YES"/"yes" nằm trong CONFIRM_PHRASES, nếu để sau sẽ
            #    bị bắt nhầm thành lệnh chốt gửi timesheet.
            if (state.get("conversation", {}) or {}).get("awaiting") == "reset_notes_confirm":
                if text.strip().upper() == RESET_NOTES_CONFIRM:
                    log.info("/resetnotes: bắt đầu xóa...")
                    try:
                        import daily_store as _ds
                        import shutil as _sh
                        from datetime import datetime as _dt
                        _stamp = _dt.now().strftime("%Y%m%d_%H%M%S")

                        n_before = (sum(1 for l in
                            notes_store.NOTES_FILE.read_text(encoding="utf-8").splitlines()
                            if l.strip()) if notes_store.NOTES_FILE.exists() else 0)
                        log.info("/resetnotes: tìm thấy %d ghi chú", n_before)

                        # BACKUP notes.jsonl trước khi xóa
                        notes_bak = None
                        if notes_store.NOTES_FILE.exists():
                            from config_loader import NOTES_BAK_DIR as _NBD
                            _NBD.mkdir(parents=True, exist_ok=True)
                            _nb = _NBD / f"notes.jsonl.bak_{_stamp}"
                            try:
                                _sh.copy2(notes_store.NOTES_FILE, _nb)
                                notes_bak = _nb.name
                                log.info("/resetnotes: backup notes -> %s", notes_bak)
                            except OSError as _e:
                                log.warning("/resetnotes: backup notes lỗi (%s)", _e)

                        # BACKUP parsed_days.json trước khi xóa
                        parsed_bak = None
                        if _ds.PARSED_FILE.exists():
                            from config_loader import PARSED_BAK_DIR as _PBD
                            _PBD.mkdir(parents=True, exist_ok=True)
                            _pb = _PBD / f"parsed_days.json.bak_{_stamp}"
                            try:
                                _sh.copy2(_ds.PARSED_FILE, _pb)
                                parsed_bak = _pb.name
                                log.info("/resetnotes: backup parsed_days -> %s",
                                         parsed_bak)
                            except OSError as _e:
                                log.warning("/resetnotes: backup parsed_days lỗi (%s)",
                                            _e)

                        # Xóa
                        notes_store.NOTES_FILE.write_text("", encoding="utf-8")
                        log.info("/resetnotes: đã xóa notes.jsonl")
                        _ds.PARSED_FILE.unlink(missing_ok=True)
                        log.info("/resetnotes: đã xóa parsed_days.json")
                        state["conversation"] = None
                        state["last_questions"] = None
                        state["draft"] = None
                        state["past_edit"] = None
                        state_mod.save_state(state)
                        log.info("/resetnotes: đã reset state")
                        audit("NOTES_RESET_ALL",
                              f"xóa {n_before} ghi chú + parsed_days "
                              f"(backup: {notes_bak}, {parsed_bak})")
                        await update.effective_message.reply_text(
                            f"✅ Đã xóa toàn bộ {n_before} ghi chú "
                            f"và cache parse.\n"
                            f"📁 Backup: {notes_bak or '(không có)'}, "
                            f"{parsed_bak or '(không có)'}\n\n"
                            f"File Excel timesheet đã gửi KHÔNG bị ảnh hưởng.\n"
                            f"Nhắn lại ghi chú từ đầu nhé bro!")
                    except Exception as e:
                        log.exception("/resetnotes: lỗi khi xóa")
                        state["conversation"] = None
                        state_mod.save_state(state)
                        await update.effective_message.reply_text(
                            f"Xóa bị lỗi ({type(e).__name__}: {e}). "
                            f"Xem log để biết thêm.")
                else:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Đã hủy. Ghi chú vẫn nguyên vẹn.")
                return

            # 1) CHỐT GỬI (ưu tiên bản sửa quá khứ nếu đang chờ)
            if normalized in CONFIRM_PHRASES:
                if state.get("past_edit"):
                    audit("CMD_CONFIRM_PAST_EDIT", text)
                    await update.effective_message.reply_text(
                        "Ok, đang sửa file đã gửi…")
                    result = await asyncio.to_thread(
                        orchestrator.apply_past_edit, config, state)
                    await update.effective_message.reply_text(
                        "Đã sửa xong: " + ", ".join(result["files"])
                        + "\n\nBản sửa sẽ đi kèm chuyến gửi thứ 6 tới. "
                        "Muốn gửi lại cho sếp ngay thì nhắn \"gởi lại\".")
                    return
                if not draft_pending:
                    await update.effective_message.reply_text(
                        "Chưa có bản nháp nào chờ duyệt bro. Muốn chốt sớm "
                        "thì nhắn: gởi timesheet tới hôm nay.")
                    return
                audit("CMD_CONFIRM", text)
                # BƯỚC REVIEW EMAIL: hiện nội dung email + D/E/F trước khi gửi
                await update.effective_message.reply_text(
                    "Đang soạn email timesheet để bro xem trước…")
                prev = await asyncio.to_thread(
                    orchestrator.prepare_send_preview, config, state)
                if prev.get("status") == "review":
                    state["conversation"] = {"awaiting": "ts_mail_confirm"}
                    state_mod.save_state(state)
                    await _reply_long(update, prev["preview"])
                    return
                elif prev.get("status") == "need_info":
                    await _reply_long(update,
                        "\n".join(f"• {q}" for q in prev.get("questions", [])))
                    return
                elif prev.get("status") == "already_sent":
                    await update.effective_message.reply_text(
                        "Tuần này đã gửi rồi bro.")
                    return
                else:
                    # fallback: gửi thẳng (không tạo được preview)
                    result = await asyncio.to_thread(
                        orchestrator.finalize_and_send, config, state)
                    await _reply_result(update, result)
                return

            # 2) KHOAN GỞI / BỎ KHOAN
            if normalized in UNHOLD_PHRASES:
                state["hold"] = False
                state_mod.save_state(state)
                audit("CMD_UNHOLD", "")
                await update.effective_message.reply_text(
                    "Đã bỏ khoan. Có nháp thì bro cứ ok là mình gửi.")
                return
            if ("khoan" in normalized
                    and ("gởi" in normalized or "gửi" in normalized))                     or normalized == "/hold":
                state["hold"] = True
                state_mod.save_state(state)
                audit("CMD_HOLD", "")
                await update.effective_message.reply_text(
                    "Rồi, KHOAN GỞI. Mình giữ lại tới khi bro ok, kể cả "
                    "qua thứ 7 CN luôn.")
                return

            # 3) RESET STATUS
            if text.strip().lower() in RESET_STATUS_CMDS:
                # Ghi nhận TRẠNG THÁI TRƯỚC khi xóa để log rõ ràng
                had_conversation = bool(
                    (state.get("conversation") or {}).get("awaiting"))
                had_questions = bool(state.get("last_questions"))
                had_draft = bool(state.get("draft"))
                had_past_edit = bool(state.get("past_edit"))

                state["conversation"] = None
                state["last_questions"] = None
                state["draft"] = None
                state["past_edit"] = None
                state_mod.save_state(state)

                detail = (
                    f"conversation={had_conversation}, "
                    f"last_questions={had_questions}, "
                    f"draft={had_draft}, "
                    f"past_edit={had_past_edit}")
                log.info("/resetstatus: %s", detail)
                audit("RESET_STATUS", detail)

                # Thông báo chi tiết những gì đã reset
                lines = []
                if had_conversation:
                    lines.append("✓ Đang chờ bổ sung → đã xóa")
                if had_questions:
                    lines.append("✓ Câu hỏi treo → đã xóa")
                if had_draft:
                    lines.append("✓ Bản nháp chờ duyệt → đã xóa")
                if had_past_edit:
                    lines.append("✓ Bản sửa quá khứ → đã xóa")

                if lines:
                    msg = ("Reset status xong bro:\n"
                           + "\n".join(lines)
                           + "\n\nGhi chú vẫn nguyên.")
                else:
                    msg = "Status đã sạch rồi, không có gì để reset bro."

                await update.effective_message.reply_text(msg)
                return

            # 4) RESET NOTES — bước 1: hỏi xác nhận
            if text.strip().lower() in RESET_NOTES_CMDS:
                audit("CMD_RESET_NOTES_REQUEST", "đang chờ xác nhận")
                state["conversation"] = {"awaiting": "reset_notes_confirm"}
                state_mod.save_state(state)
                n_total = sum(
                    1 for l in open(notes_store.NOTES_FILE, encoding="utf-8")
                    if l.strip()) if notes_store.NOTES_FILE.exists() else 0
                await update.effective_message.reply_text(
                    f"⚠️ Bro sắp XÓA TOÀN BỘ {n_total} ghi chú "
                    f"(tất cả các kỳ) và toàn bộ cache parse.\n\n"
                    f"Dữ liệu Excel timesheet đã gửi KHÔNG bị ảnh hưởng.\n\n"
                    f"Nhắn '{RESET_NOTES_CONFIRM}' (viết hoa) để xác nhận, "
                    f"hoặc bất kỳ thứ gì khác để hủy.")
                return

            # 4b) FORCE SEND — bypass validation (xác nhận 2 bước)
            if normalized in FORCE_SEND_PHRASES:
                # Bước 1: hỏi xác nhận với danh sách lỗi hiện tại
                draft = state.get("draft")
                if not draft:
                    await update.effective_message.reply_text(
                        "Chưa có bản nháp nào để gởi bro. "
                        "Nhắn 'gởi timesheet tới hôm nay' để soạn trước.")
                    return
                # Lấy danh sách lỗi hiện tại từ draft
                pending_issues = state.get("last_questions") or []
                if not pending_issues:
                    # Không có lỗi → gửi bình thường
                    await update.effective_message.reply_text(
                        "Không có lỗi nào cần bypass. Nhắn 'ok' để gởi bình thường.")
                    return
                issues_text = "\n".join(f"• {q}" for q in pending_issues)
                state["conversation"] = {"awaiting": "force_send_confirm"}
                state_mod.save_state(state)
                audit("FORCE_SEND_REQUESTED", f"{len(pending_issues)} lỗi")
                await _reply_long(update,
                    f"⚠️ Vẫn còn {len(pending_issues)} vấn đề:\n"
                    f"{issues_text}\n\n"
                    f"Nhắn '{FORCE_SEND_CONFIRM}' để bỏ qua lỗi và gởi, "
                    "hoặc bất kỳ thứ gì khác để hủy.")
                return

            # 4c) XÁC NHẬN FORCE SEND
            if (state.get("conversation", {}) or {}).get("awaiting") == "force_send_confirm":
                if text.strip().upper() == FORCE_SEND_CONFIRM:
                    audit("FORCE_SEND_CONFIRMED", "bypass validation")
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Ok, đang bỏ qua validation và gởi mail…")
                    result = await asyncio.to_thread(
                        orchestrator.finalize_and_send, config, state,
                        force=True)
                    await _reply_result(update, result)
                else:
                    state["conversation"] = None
                    state_mod.save_state(state)
                    await update.effective_message.reply_text(
                        "Đã hủy. Bản nháp vẫn còn đó, nhắn lại khi cần.")
                return

            # 5) GỬI LẠI  (câu 'gởi lại' — dùng chung với lệnh /resend)
            if normalized in RESEND_PHRASES:
                audit("CMD_RESEND", text)
                await _start_resend(update, state)
                return

            # 5b) AI DETECT FORCE SEND từ ngôn ngữ tự nhiên
            # Chỉ chạy khi: có pending validation errors VÀ text ngắn
            # (câu dài = ghi chú bình thường, không phải lệnh gởi)
            pending_qs = state.get("last_questions") or []
            has_send_word = any(w in normalized for w in
                                ["gởi", "gửi", "send", "thôi", "kệ",
                                 "bỏ qua", "bypass", "chấp nhận"])
            if (pending_qs and has_send_word and len(text) < 80
                    and normalized not in CONFIRM_PHRASES
                    and normalized not in RESEND_PHRASES):
                try:
                    detect_prompt = _FORCE_SEND_DETECT_PROMPT.format(
                        text=text[:200])
                    raw = ai_client.generate_json(
                        detect_prompt, purpose="daily", config=config,
                        session="force_detect")
                    if raw.get("want_force_send"):
                        # AI xác nhận ý định force → hỏi xác nhận 2 bước
                        issues_text = "\n".join(
                            f"• {q}" for q in pending_qs)
                        state["conversation"] = {
                            "awaiting": "force_send_confirm"}
                        state_mod.save_state(state)
                        audit("FORCE_SEND_AI_DETECTED", text[:80])
                        await _reply_long(update,
                            f"Mình hiểu bro muốn gởi dù còn "
                            f"{len(pending_qs)} vấn đề:\n"
                            f"{issues_text}\n\n"
                            f"Nhắn '{FORCE_SEND_CONFIRM}' để xác nhận "
                            "bỏ qua lỗi và gởi, hoặc nhắn gì khác để hủy.")
                        return
                except Exception as _e:  # noqa: BLE001 — detect hỏng thì ghi chú bình thường
                    log.debug("Force send AI detect lỗi (%s) — xử lý như ghi chú thường.", _e)

            # 5b-preview) XÓA FILE PREVIEW bằng ngôn ngữ tự nhiên
            #    → tương đương /deletedraft. Bắt trước handler ghi chú.
            if normalized in DELETE_PREVIEW_PHRASES:
                await cmd_delete_draft(update, context)
                return

            # 5c) SOẠN BẢN NHÁP SỚM — KHÔNG lưu vào notes
            # "gởi timesheet tới hôm nay" → /createdraft tương đương
            # Phải bắt TRƯỚC handler ghi chú để tránh lưu vào notes
            if normalized in EARLY_SEND_PHRASES:
                audit("CMD_EARLY_SEND", text)
                await update.effective_message.reply_text(
                    "Đang soạn bản nháp timesheet…")
                # Thứ 2–6: chốt TỚI HÔM NAY. Thứ 7/CN: chốt theo thứ 6 vừa qua.
                # (Sửa 30-Sep: trước không truyền ngày → thứ 2–5 tự lùi về thứ 6
                # TUẦN TRƯỚC → báo nhầm "đã gửi".)
                _t = date.today()
                _early_day = _t if _t.weekday() <= 4 else None
                try:
                    result = await asyncio.to_thread(
                        orchestrator.prepare_draft, config,
                        state_mod.load_state(), False, _early_day)
                except Exception as e:
                    log.exception("early_send lỗi")
                    await update.effective_message.reply_text(
                        f"Lỗi soạn bản nháp: {type(e).__name__}: {e}")
                    return
                if result.get("status") == "already_sent":
                    await update.effective_message.reply_text(
                        "Các ngày tới hôm nay đã gửi sếp rồi bro. Sửa ngày đã "
                        "gửi: /edittimesheet → rồi /resend để gởi lại bản mới.")
                elif result.get("status") == "need_info":
                    # (07-Oct, B6) KHÔNG ghi `result` (danh sách câu hỏi) vào ô bản
                    # nháp: trước đây 'ok' sau đó báo "không có dữ liệu tháng nào" và
                    # /status lỗi. prepare_draft đã tự lưu trạng thái đúng.
                    qs = result.get("questions", [])
                    await _reply_long(update,
                        f"Còn {len(qs)} vấn đề cần giải quyết:\n"
                        + "\n".join(f"• {q}" for q in qs)
                        + "\n\nBro điền bổ sung (nhắn như ghi chú bình thường), xong "
                        "nhắn lại \"gởi timesheet tới hôm nay\" để mình soạn bản nháp. "
                        "Muốn bỏ qua lỗi: /forcedraft.")
                else:
                    # prepare_draft ĐÃ tự lưu bản nháp thật vào state. KHÔNG ghi đè
                    # bằng `result` (có danh sách file kiểu Path → lỗi khi lưu JSON,
                    # và làm mất bản nháp thật). Giống /createdraft. (Sửa 28-Sep)
                    preview = result.get("preview", "")
                    await _reply_long(update,
                        f"Đã soạn bản nháp:\n\n{preview[:1200]}"
                        + "\n\nNhắn 'ok' để gửi mail cho sếp.")
                return

            # 6) GHI CHÚ THƯỜNG — dùng note_action (bóc 1 tin → action)
            # KHÔNG parse lại cả kỳ nữa (tránh AI lú vì đọc đống notes cũ).
            # Vẫn LƯU notes.jsonl làm log thô (thứ 6 rule_parser dự phòng).
            _sent_at = _sent_at_local(update)
            audit("NOTE_SAVED", f"{_sent_at.date()}: {text[:100]}")
            record = notes_store.add_note(text, sent_at=_sent_at)
            # Đưa CÂU GỐC (không phải bản đã chuẩn hóa trong notes) vào bóc
            # tách, kèm NGÀY TIN NHẮN làm "hôm nay". (Sửa 25-Sep: bản chuẩn hóa
            # bị chuẩn hóa lần 2 → mất cụm "thứ 2 tới thứ 3 tuần rồi" → sai ngày)
            await _handle_note_action(update, state, text, sent_day=_sent_at.date())

        except KNOWN_ERRORS as e:
            log.warning("Lỗi nghiệp vụ đã biết: %s: %s", type(e).__name__, e)
            audit("HANDLER_ERROR", f"{type(e).__name__}: {e}")
            await update.effective_message.reply_text(str(e))
        except _TG_NET_ERRORS as e:
            # Mất mạng lúc bot đang TRẢ LỜI → không cố gửi thêm (cũng sẽ hỏng)
            log.warning("Mất kết nối Telegram khi trả lời (%s) — tin trả lời có thể "
                        "chưa tới; bot vẫn chạy, đang thử lại.", type(e).__name__)
            audit("TG_NETWORK", f"khi trả lời: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            log.exception("Lỗi xử lý lệnh (CHƯA TỪNG GẶP).")
            audit("HANDLER_ERROR", f"{type(e).__name__}: {e}")
            await update.effective_message.reply_text(
                f"Hỏng rồi bro, lệnh này bị lỗi lạ ({type(e).__name__}). "
                "Chi tiết trong data\\logs\\timesheet.log — thử lại hoặc "
                "chụp log cho Claude nhé.")




async def _handle_note_action(update, state: dict, text: str, sent_day=None):
    """Xử lý 1 tin ghi chú bằng note_action (bóc action → validate →
    ghi luôn NẾU không cần xác nhận, HOẶC hỏi xác nhận trước).

    Ngày trong kỳ (chưa gửi): ghi parsed_days.
    Ngày đã gửi: cũng ghi Excel (also_excel_if_sent=True).
    """
    import ai_client as _ai
    try:
        acts, not_act = await asyncio.to_thread(
            note_action.parse_actions, text, config, None, sent_day)
    except _ai.AIError as e:
        log.warning("note_action parse lỗi (%s) — fallback rule_parser.", e)
        # Fallback: rule_parser (tầng 3) khi AI sập
        await _fallback_rule_parser(update, state, text, e, sent_day=sent_day)
        return

    if not_act or not acts:
        # Không phải action timesheet (ok/cảm ơn...) → không làm gì thêm
        # (các phrase điều khiển đã được handler phía trên bắt rồi)
        await update.effective_message.reply_text("Đã ghi chú nha bro.")
        return

    pd = daily_store.load_all()
    acts = note_action.validate_actions(acts, pd, config)

    # CHẶN: ghi chú thường KHÔNG được đụng ngày đã gửi sếp (cả cụm bị chặn
    # nếu 1 ngày trong cụm đã gửi — không ghi nửa vời)
    _sent = _sent_days_in_actions(acts, state)
    if _sent:
        audit("NL_EDIT_BLOCKED_SENT_DAY", ", ".join(d.isoformat() for d in _sent))
        await _reply_long(update, _block_sent_days_msg(_sent, state))
        return

    # Nếu MỌI action đều error → báo lỗi
    if all(a.error for a in acts):
        await _reply_long(update,
            "Chưa xử lý được:\n"
            + "\n".join(f"• {a.error}" for a in acts if a.error))
        return

    # Nếu có action cần xác nhận (delete/replace/trùng) → hỏi trước
    if any(a.needs_confirm for a in acts if not a.error):
        state["conversation"] = {
            "awaiting": "past_edit_confirm",
            "source": "nl",     # từ ghi chú thường → vẫn chặn ngày đã gửi
            "note_actions": _serialize_actions(acts)}
        state_mod.save_state(state)
        await _reply_long(update, note_action.format_preview(acts))
        return

    # Không cần xác nhận → ghi luôn
    try:
        res = await asyncio.to_thread(
            note_action.persist_actions, acts, config,
            state_mod.load_state(), True)
    except Exception as e:  # noqa: BLE001
        log.exception("note_action persist lỗi")
        await update.effective_message.reply_text(
            f"Ghi lỗi ({type(e).__name__}: {e}).")
        return

    # Bản nháp cũ đã HỦY vì sửa ngày trong kỳ (02-Oct) → xóa cả trong `state`
    # đang giữ, để lần lưu sau KHÔNG ghi bản nháp cũ trở lại.
    if res.get("draft_invalidated"):
        state["draft"] = None
        if (state.get("conversation") or {}).get("awaiting") == "ts_mail_confirm":
            state["conversation"] = None
        state_mod.save_state(state)

    # Nhớ tháng đã sửa nếu có ngày đã gửi
    if res.get("excel_months"):
        state["last_edited_months"] = res["excel_months"]
        state_mod.save_state(state)

    # Thông báo CHI TIẾT (hiện task từng ngày đã ghi, không chỉ "đã ghi ngày X")
    msg = note_action.format_result(res)
    if res.get("excel_files"):
        msg += ("\n📁 Ngày đã gửi → cũng cập nhật Excel. Nhắn 'gởi lại' "
                "nếu muốn gửi sếp bản mới.")
    if res.get("draft_invalidated"):
        msg += "\n\n" + "⚠️ Bản nháp timesheet đang chờ gửi có chứa ngày bro vừa sửa → bản nháp CŨ đã được HỦY (để không gửi nhầm bản chưa sửa). Gõ /createdraft để soạn lại bản nháp mới (file Excel xem trước nằm trong data\\preview), rồi 'ok' → 'ok' để gửi."
    await _reply_long(update, msg)


def _queue_pending_note(state: dict, text: str, reason: str, sent_day=None) -> int:
    """Giữ lại tin mà cả AI lẫn rule đều không bóc được (thêm 24-Sep).
    Trước đây tin chỉ nằm trong notes.jsonl: thứ 6 chỉ đọc lại notes cho
    NGÀY CHƯA CÓ dữ liệu → câu SỬA ngày đã có bị mất âm thầm; và notes
    bị xóa sau khi gửi. Nay: hàng chờ riêng trong state + CHẶN tạo nháp/
    gửi cho tới khi xử lý hết (/retrynotes)."""
    q = list(state.get("pending_notes") or [])
    if not any(p.get("text") == text for p in q):
        q.append({"text": text, "reason": reason,
                  "at": datetime.now().isoformat(timespec="minutes"),
                  "sent_day": (sent_day or date.today()).isoformat()})
    state["pending_notes"] = q
    state_mod.save_state(state)
    audit("NOTE_PENDING", f"{len(q)} tin chờ: {text[:60]}")
    return len(q)


async def _fallback_rule_parser(update, state: dict, text: str, ai_err,
                                source: str = "nl", sent_day=None):
    """AI lỗi → bóc bằng rule_parser, rồi đi qua CÙNG validate / chặn ngày
    đã gửi / preview như đường AI (luôn bắt 'ok' vì rule kém hơn AI).
    Rule cũng không bóc được:
      - /edittimesheet (source='edit'): báo, giữ nguyên chờ nhập lại
      - ghi chú thường (source='nl'): đưa vào hàng chờ /retrynotes"""
    log.warning("AI lỗi (%s) — thử rule_parser (%s).", ai_err, source)
    try:
        acts, reason = await asyncio.to_thread(
            note_action.actions_from_rule_parser, text, sent_day)
    except Exception as _e:  # noqa: BLE001
        log.exception("rule_parser fallback lỗi")
        acts, reason = [], f"rule lỗi ({type(_e).__name__})"
    if acts:
        acts = note_action.validate_actions(acts, daily_store.load_all(), config)
        if source == "nl":
            _sent = _sent_days_in_actions(acts, state)
            if _sent:
                await _reply_long(update, _block_sent_days_msg(_sent, state))
                return
        if all(a.error for a in acts):
            # Lỗi KIỂM TRA (vd "không thấy ngày 30/9 để xóa") là câu trả lời
            # dứt khoát, không liên quan mạng → báo thẳng, KHÔNG đưa vào hàng chờ.
            await _reply_long(update, "Chưa xử lý được:\n"
                              + "\n".join(f"• {a.error}" for a in acts if a.error))
            return
    if acts:
        state["conversation"] = {"awaiting": "past_edit_confirm",
                                 "source": source,
                                 "note_actions": _serialize_actions(acts)}
        state_mod.save_state(state)
        audit("RULE_PARSER_OK", f"{source}: {len(acts)} action")
        await _reply_long(update,
            ("✂️ AI trả lời quá dài nên bị cắt" if "bị CẮT" in str(ai_err)
             else "🔌 AI đang lỗi mạng")
            + " — mình tự bóc tách bằng rule (luật dự phòng "
            "LUÔN hỏi lại trước khi ghi / sửa / xóa):\n\n"
            + note_action.format_preview(acts))
        return
    if source == "edit":
        await update.effective_message.reply_text(
            f"🔌 AI đang lỗi mạng, và rule không bóc được câu này ({reason}). "
            "CHƯA ghi gì. Thử lại sau vài phút, ghi rõ ngày dd/mm + task, "
            "hoặc nhắn 'hủy' để thoát.")
        return
    n = _queue_pending_note(state, text, reason, sent_day)
    await update.effective_message.reply_text(
        f"🔌 AI đang lỗi mạng, và rule không bóc được câu này ({reason}).\n"
        "→ CHƯA ghi vào timesheet. Mình đã GIỮ LẠI tin này "
        f"(đang có {n} tin chờ).\n"
        "Khi mạng ổn, nhắn /retrynotes để xử lý lại.\n"
        "Bot sẽ KHÔNG cho tạo nháp / gửi timesheet cho tới khi hết tin chờ "
        "→ không sợ bị sót.")


def _sent_days_in_actions(acts: list, state: dict) -> list:
    """Ngày ĐÍCH (ngày bị ghi/sửa/xóa) nằm trong kỳ ĐÃ GỬI sếp
    (<= last_sent). Ngày NGUỒN của COPY_FROM không tính (copy TỪ ngày cũ
    là bình thường). Dùng để chặn sửa ngày đã gửi bằng ngôn ngữ tự nhiên."""
    last = state_mod.last_sent_date(state)
    if last is None:
        return []
    days = sorted({a.day for a in acts
                   if a.day and not a.error and a.day <= last})
    return days


def _block_sent_days_msg(days: list, state: dict) -> str:
    last = state_mod.last_sent_date(state)
    ds = ", ".join(note_action._dmy(d) for d in days)
    return (
        "⛔ KHÔNG sửa bằng ghi chú thường được — có ngày đã GỬI SẾP:\n"
        f"  {ds}\n"
        f"(timesheet đã gửi tới {last.strftime('%d/%m/%Y')}).\n\n"
        "Ngày đã gửi phải sửa bằng /edittimesheet — lệnh đó sửa CẢ file "
        "Excel lẫn parsed_days, rồi gõ /resend để gửi sếp bản mới.\n"
        "Không có gì bị ghi. Ngày chưa gửi trong tuần này vẫn sửa bằng "
        "ghi chú bình thường.")


def _serialize_actions(acts: list) -> list:
    """Chuyển list Action → list dict để lưu vào state.json (JSON-safe)."""
    out = []
    for a in acts:
        out.append({
            "type": a.type,
            "day": a.day.isoformat() if a.day else None,
            "tasks": a.tasks,
            "copy_from": a.copy_from.isoformat() if a.copy_from else None,
            "needs_confirm": a.needs_confirm,
            "confirm_msg": a.confirm_msg,
            "error": a.error,
            "warning": a.warning,
        })
    return out


def _deserialize_actions(data: list) -> list:
    """Chuyển list dict từ state.json → list Action."""
    from datetime import date as _date
    acts = []
    for d in data:
        day = _date.fromisoformat(d["day"]) if d.get("day") else None
        cf = _date.fromisoformat(d["copy_from"]) if d.get("copy_from") else None
        acts.append(note_action.Action(
            type=d["type"], day=day, tasks=d.get("tasks", []),
            copy_from=cf, needs_confirm=d.get("needs_confirm", False),
            confirm_msg=d.get("confirm_msg", ""), error=d.get("error", ""),
            warning=d.get("warning", "")))
    return acts


def _fingerprint(rows: list) -> set:
    """Dấu vân tay 1 ngày để biết có thay đổi thật hay không."""
    return {(e["project"], e["task"], e.get("description", ""),
             round(float(e["hours"]), 2)) for e in rows}



def _format_summary(entries_by_day: dict,
                    title: str, period_label: str) -> list:
    """Định dạng parsed_days thành danh sách tin nhắn (không gọi AI)."""
    if not entries_by_day:
        return [f"{title}\n\nChưa có dữ liệu cho {period_label} bro."]

    thu_names = ["Thứ Hai","Thứ Ba","Thứ Tư",
                 "Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ nhật"]

    from collections import defaultdict
    import re as _re
    from datetime import date as _date

    by_month = defaultdict(list)
    for day_str, day_data in sorted(entries_by_day.items()):
        by_month[day_str[:7]].append((day_str, day_data))

    lines_all = [f"📋 {title}"]
    total_h_all = 0.0

    for month_key in sorted(by_month):
        year, mon = month_key.split("-")
        lines_all.append(f"\n━━━ Tháng {int(mon)}/{year} ━━━")
        total_h_month = 0.0

        for day_str, day_data in by_month[month_key]:
            d = _date.fromisoformat(day_str)
            thu = thu_names[d.weekday()]
            day_entries = day_data.get("entries", [])
            total_h_day = sum(float(e.get("hours", 0)) for e in day_entries)
            total_h_month += total_h_day
            total_h_all   += total_h_day

            lines_all.append(
                f"\n📅 {thu}, {d.strftime('%d/%m/%Y')} — tổng {total_h_day:g}h")

            for e in sorted(day_entries, key=lambda x: x.get("task","")):
                h    = e.get("hours", 0)
                task = e.get("task", "?")
                proj = e.get("project", "?")
                desc = e.get("description", "") or ""

                # Hiện NGUYÊN VĂN mô tả như đã lưu = y hệt cột F trong Excel / email.
                # (Sửa 28-Sep: trước tách mã ra "🎫" rồi XÓA mã khỏi mô tả → còn
                # trơ "Ticket # : …", gộp dấu phẩy, mã sai định dạng lẫn lộn.)
                line = f"  • {h:g}h [{task}] {proj}"
                if desc:
                    line += f" | {desc}"
                lines_all.append(line)

        lines_all.append(f"  📊 Tháng {int(mon)}: {total_h_month:g}h")

    lines_all.append(f"\n✅ TỔNG: {total_h_all:g}h")

    # Cắt thành các tin ≤ 3800 ký tự
    full = "\n".join(lines_all)
    if len(full) <= 3800:
        return [full]

    parts, cur, cur_len = [], [lines_all[0]], len(lines_all[0])
    for line in lines_all[1:]:
        if cur_len + len(line) + 1 > 3800:
            parts.append("\n".join(cur))
            cur, cur_len = [f"📋 {title} (tiếp)", line], len(line) + len(title) + 12
        else:
            cur.append(line); cur_len += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts


async def cmd_summary(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """/summary — Tổng hợp TẤT CẢ công việc từ parsed_days (không gọi AI)."""
    if not is_allowed(update):
        return
    try:
        data = daily_store.load_all()
    except Exception as e:
        log.warning("cmd_summary lỗi đọc (%s)", e)
        data = {}
    if not data:
        await update.effective_message.reply_text(
            "Chưa có dữ liệu parse nào bro. Nhắn ghi chú trước nhé.")
        return
    audit("CMD_SUMMARY", f"{len(data)} ngày")
    for part in _format_summary(data, "TỔNG HỢP CÔNG VIỆC", "kỳ này"):
        await update.effective_message.reply_text(part)


async def cmd_summary_week(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/summaryweek — Tổng hợp công việc TUẦN NÀY từ parsed_days (không gọi AI)."""
    if not is_allowed(update):
        return
    from datetime import date as _d, timedelta as _td
    today = _d.today()
    try:
        state = state_mod.load_state()
        last_sent = state_mod.last_sent_date(state)
        week_start = (last_sent + _td(1)) if last_sent                      else (today - _td(today.weekday()))
        # BUG cũ: lấy tới today → thiếu ngày sau today (vd nhập T5,T6
        # trước khi tới ngày đó). Nay lấy tới CUỐI TUẦN (thứ 6) của
        # tuần chứa today, để hiện đủ mọi ngày đã nhập trong tuần.
        monday_this = today - _td(today.weekday())
        week_end = monday_this + _td(4)   # thứ 6
        if week_end < today:              # phòng trường hợp lạ
            week_end = today
        data_all  = daily_store.load_all()
        data_week = {k: v for k, v in data_all.items()
                     if week_start.isoformat() <= k <= week_end.isoformat()}
    except Exception as e:
        log.warning("cmd_summary_week lỗi (%s)", e)
        await update.effective_message.reply_text(
            f"Lỗi đọc dữ liệu ({type(e).__name__}). Xem log nha bro.")
        return
    if not data_week:
        await update.effective_message.reply_text(
            "Chưa có dữ liệu tuần này bro.")
        return
    label = (f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}")
    audit("CMD_SUMMARY_WEEK", label)
    for part in _format_summary(data_week, f"TUẦN {label}", label):
        await update.effective_message.reply_text(part)



# ---------------------------------------------------------------------------
# LỆNH ĐIỀU KHIỂN KHÔNG CẦN AI
# ---------------------------------------------------------------------------

async def cmd_validate_notes(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """/checknotes — Validate toàn bộ parsed_days hiện tại (D/E/F rules).
    Không cần AI. Chỉ đọc parsed_days.json và chạy validate_task_rules."""
    if not is_allowed(update): return
    audit("CMD_CHECKNOTES", "")
    try:
        data = daily_store.load_all()
    except Exception as e:
        await update.effective_message.reply_text(f"Lỗi đọc parsed_days: {e}")
        return
    if not data:
        await update.effective_message.reply_text("parsed_days.json trống bro.")
        return

    all_entries = []
    for day_str, day_data in sorted(data.items()):
        for e in day_data.get("entries", []):
            entry = dict(e)
            entry["date"] = date.fromisoformat(day_str)
            all_entries.append(entry)

    errors = validator.validate_task_rules(all_entries, is_friday=False)
    if not errors:
        await update.effective_message.reply_text(
            f"✅ Tất cả {len(data)} ngày, {len(all_entries)} task — "
            f"không có lỗi D/E/F nào bro!")
    else:
        msg = (f"⚠️ Tìm thấy {len(errors)} vấn đề trong {len(data)} ngày:\n\n"
               + "\n".join(f"• {e}" for e in errors[:20]))
        if len(errors) > 20:
            msg += f"\n...và {len(errors)-20} vấn đề khác"
        await _reply_long(update, msg)


async def cmd_create_draft(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/createdraft — Tạo bản nháp Excel từ parsed_days (không gửi mail).
    Không cần AI. Tương đương chạy weekly_run nhưng chỉ dừng ở bước Excel."""
    if not is_allowed(update): return
    audit("CMD_CREATEDRAFT", "")
    await update.effective_message.reply_text("Đang tạo bản nháp Excel…")
    try:
        result = await asyncio.to_thread(
            orchestrator.prepare_draft, config, state_mod.load_state())
    except Exception as e:
        log.exception("cmd_create_draft lỗi")
        await update.effective_message.reply_text(
            f"Lỗi tạo bản nháp: {type(e).__name__}: {e}")
        return
    status = result.get("status")
    if status == "already_sent":
        await update.effective_message.reply_text(
            f"Tuần {result.get('send_day','này')} ĐÃ GỬI cho sếp rồi bro — "
            "không cần tạo draft nữa.\n\n"
            "• Muốn gửi LẠI file tuần này (vd sau khi sửa số liệu) → "
            "nhắn 'gởi lại'.\n"
            "• Muốn sửa 1 ngày đã gửi → nhắn ngày + việc mới "
            "(vd 'thứ 3 làm DFU PACSDFUM-4865'), bot soạn bản sửa.")
    elif status == "need_info":
        qs = result.get("questions", [])
        await _reply_long(update,
            f"⚠️ Còn {len(qs)} vấn đề validation:\n"
            + "\n".join(f"• {q}" for q in qs)
            + "\n\nDùng /forcedraft để bỏ qua và tạo thẳng.")
    elif status == "ready":
        preview = result.get("preview", "")
        await _reply_long(update,
            f"✅ Bản nháp Excel tạo xong!\n\n{preview[:800]}"
            + "\n\nNhắn /sendmail để gửi, hoặc /checkdraft để xem lại.")
    else:
        await update.effective_message.reply_text(
            f"Trạng thái không rõ: {status}")


async def cmd_force_draft(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/forcedraft — Tạo bản nháp Excel dù còn lỗi validation."""
    if not is_allowed(update): return
    audit("CMD_FORCEDRAFT", "bypass validation")
    await update.effective_message.reply_text("Đang tạo bản nháp (bỏ qua validation)…")
    try:
        result = await asyncio.to_thread(
            orchestrator.prepare_draft, config, state_mod.load_state(),
            force=True)
    except Exception as e:
        log.exception("cmd_force_draft lỗi")
        await update.effective_message.reply_text(f"Lỗi: {type(e).__name__}: {e}")
        return
    status = result.get("status")
    if status == "already_sent":
        await update.effective_message.reply_text(
            f"Tuần {result.get('send_day','này')} ĐÃ GỬI cho sếp rồi bro.\n\n"
            "• Gửi LẠI file tuần này → 'gởi lại'.\n"
            "• Sửa 1 ngày đã gửi → nhắn ngày + việc mới, bot soạn bản sửa.")
        return
    if status == "need_info":
        # force=True mà vẫn need_info → thường do kỳ rỗng
        qs = result.get("questions", [])
        await _reply_long(update,
            "Không tạo được bản nháp:\n"
            + "\n".join(f"• {q}" for q in qs))
        return
    preview = result.get("preview", "")
    await _reply_long(update,
        f"✅ Bản nháp tạo xong (đã bỏ qua validation).\n\n"
        f"{preview[:800]}\n\nNhắn /sendmail khi ưng.")


async def cmd_check_draft(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/checkdraft — Xem lại bản nháp Excel hiện tại + validate."""
    if not is_allowed(update): return
    audit("CMD_CHECKDRAFT", "")
    state = state_mod.load_state()
    draft = state.get("draft")
    if not draft:
        await update.effective_message.reply_text(
            "Chưa có bản nháp nào. Nhắn /createdraft để tạo.")
        return
    preview = draft.get("preview", "(không có preview)")
    questions = draft.get("questions") or []
    msg = f"📋 Bản nháp hiện tại:\n\n{preview[:1000]}"
    if questions:
        msg += f"\n\n⚠️ Còn {len(questions)} vấn đề:\n"
        msg += "\n".join(f"• {q}" for q in questions)
    else:
        msg += "\n\n✅ Không có lỗi validation."
    await _reply_long(update, msg)


async def cmd_send_mail(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sendmail — Gửi mail từ bản nháp hiện tại (cần đã có draft)."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    if not state.get("draft"):
        await update.effective_message.reply_text(
            "Chưa có bản nháp. Nhắn /createdraft trước.")
        return
    audit("CMD_SENDMAIL", "")
    await update.effective_message.reply_text("Đang gửi mail…")
    try:
        result = await asyncio.to_thread(
            orchestrator.finalize_and_send, config, state)
    except Exception as e:
        log.exception("cmd_send_mail lỗi")
        await update.effective_message.reply_text(f"Lỗi gửi: {type(e).__name__}: {e}")
        return
    await _reply_result(update, result)


async def cmd_force_send_mail(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """/forcesendmail — Gửi mail dù còn lỗi validation."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    conv = state.get("conversation") or {}
    if not state.get("draft") and conv.get("awaiting") == "resend_need_info":
        # 'gởi lại' đang bị CẢNH BÁO chặn → bỏ qua cảnh báo, VẪN xem trước + 'ok'
        months = conv.get("months") or []
        audit("CMD_FORCE_SENDMAIL", f"resend bypass validation {months}")
        prev = await asyncio.to_thread(orchestrator.prepare_resend_preview,
                                       months, config, state, True)
        if prev.get("status") != "review":
            await _reply_long(update, str(prev.get("questions") or prev))
            return
        state["conversation"] = {"awaiting": "resend_confirm", "months": months,
                                 "force": True}
        state_mod.save_state(state)
        await _reply_long(update, "(GỞI LẠI — đã BỎ QUA cảnh báo theo /forcesendmail)"
                          "\n\n" + prev["preview"])
        return
    if not state.get("draft"):
        await update.effective_message.reply_text(
            "Chưa có bản nháp. Nhắn /createdraft hoặc /forcedraft trước. "
            "(Muốn GỞI LẠI bỏ qua cảnh báo: nhắn 'gởi lại' → khi bị chặn gõ "
            "/forcesendmail hoặc 'vẫn gởi'.)")
        return
    audit("CMD_FORCE_SENDMAIL", "bypass validation")
    await update.effective_message.reply_text("Đang gửi mail (bỏ qua validation)…")
    try:
        result = await asyncio.to_thread(
            orchestrator.finalize_and_send, config, state, force=True)
    except Exception as e:
        log.exception("cmd_force_send_mail lỗi")
        await update.effective_message.reply_text(f"Lỗi: {type(e).__name__}: {e}")
        return
    await _reply_result(update, result)


async def cmd_delete_draft(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deletedraft — Xóa bản nháp (state) và backup file Excel tháng này.

    Giải thích:
    - "Bản nháp" (draft) = thông tin trong state.json — preview, danh sách
      lỗi validation. Đây là bản nháp LOGIC, không phải file Excel.
    - File Excel làm việc (LiveReport_YYYY-MM.xlsx) là file TÍCH LŨY cả tháng.
      Khi /createdraft lại: write_month_entries() tự backup file cũ vào
      backup/ rồi ghi đè — KHÔNG bao giờ báo lỗi trùng tên.
    - /deletedraft xóa state draft + backup thủ công file Excel để an tâm.
    """
    if not is_allowed(update): return
    from datetime import date as _date
    import excel_writer as _ew

    state = state_mod.load_state()
    had_draft = bool(state.get("draft"))

    # Xóa state draft
    state["draft"] = None
    state["conversation"] = None
    state_mod.save_state(state)
    audit("CMD_DELETEDRAFT", f"had_draft={had_draft}")

    # Backup thủ công file Excel tháng này (nếu tồn tại)
    month = _date.today().replace(day=1)
    excel_path = _ew.working_file_path(month)
    backup_msg = ""
    if excel_path.exists():
        import shutil
        from datetime import datetime as _dt
        from config_loader import BACKUP_DIR
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{excel_path.stem}.manual_{stamp}.xlsx"
        try:
            shutil.copy2(excel_path, backup_path)
            log.info("cmd_delete_draft: backup %s -> %s",
                     excel_path.name, backup_path.name)
            audit("EXCEL_MANUAL_BACKUP", backup_path.name)
            backup_msg = (f"\n📁 File Excel tháng {month.strftime('%m/%Y')} "
                          f"đã được backup: {backup_path.name}")
        except Exception as e:
            log.warning("cmd_delete_draft: backup lỗi (%s)", e)
            backup_msg = f"\n⚠️ Backup file Excel thất bại: {e}"
    else:
        backup_msg = (f"\n(Chưa có file Excel tháng "
                      f"{month.strftime('%m/%Y')} để backup.)")

    # Dọn file preview (bản xem thử trong data\\preview)
    preview_msg = ""
    try:
        import orchestrator as _orch
        if _orch.PREVIEW_DIR.exists():
            removed = 0
            for f in _orch.PREVIEW_DIR.glob("*.xlsx"):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
            if removed:
                preview_msg = f"\n🗑️ Đã dọn {removed} file preview."
    except Exception as _e:  # noqa: BLE001
        log.debug("Dọn preview lỗi: %s", _e)

    msg = ("✅ Đã xóa bản nháp (draft)."
           + backup_msg
           + preview_msg
           + "\n\n━━━━━━━━━━━━━━━━━━\n"
           "📌 /deletedraft XÓA những gì:\n"
           "  ✅ Xóa: bản nháp logic (state draft) + file preview\n"
           "  ✅ Backup (KHÔNG xóa): file Excel tháng\n"
           "  ❌ GIỮ NGUYÊN: parsed_days.json (dữ liệu đã parse)\n"
           "  ❌ GIỮ NGUYÊN: notes.jsonl (ghi chú thô)\n"
           "\nDữ liệu công việc của bro vẫn còn — chỉ xóa bản nháp tạm.\n"
           "Nhắn /createdraft hoặc 'gởi timesheet tới hôm nay' để tạo lại.")
    await _reply_long(update, msg)


async def cmd_edit_timesheet(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """/edittimesheet — Sửa timesheet ĐÃ GỬI (an toàn, có xác nhận).
    Bot hỏi sửa gì → AI bóc tách → xác nhận vòng lặp → ghi Excel.
    KHÔNG tự gửi mail (người dùng tự /sendmail hoặc 'gởi lại' sau)."""
    if not is_allowed(update): return
    audit("CMD_EDITTIMESHEET", "")
    state = state_mod.load_state()
    state["conversation"] = {"awaiting": "past_edit_request"}
    state_mod.save_state(state)
    await update.effective_message.reply_text(
        "🔧 Sửa timesheet (ngày đã gửi HOẶC ngày trong kỳ chưa gửi).\n\n"
        "Bro muốn sửa ngày nào, task gì? Nhắn theo dạng:\n"
        "ngày <DD/MM>: <nội dung task>\n\n"
        "Ví dụ:\n"
        "• ngày 10/9: nghỉ phép 2 tiếng, 6 tiếng làm SDF PACSGASIA-7763\n"
        "• 15/9 làm thêm DFU PACSDFUM-4865 (thêm task, giữ task cũ)\n"
        "• thứ 4 chỉ làm Coding thôi (ghi đè cả ngày)\n"
        "• xóa ngày 16/9\n\n"
        "Bot bóc thành hành động (thêm/sửa/xóa/ghi đè) → hiện lại cho bro "
        "xác nhận → 'ok' mới ghi. Sửa đi sửa lại tới khi ưng.\n"
        "• Ngày đã gửi → ghi thẳng Excel, xong nhắn 'gởi lại' cho sếp.\n"
        "• Ngày chưa gửi → ghi parsed_days, vào Excel khi /weeklyrun.\n"
        "(Nhắn 'hủy' để thoát.)")


def _leave_status_line() -> str:
    try:
        r = leave_balance.compute_balance(config)
        s = (f"Phép còn: Annual {leave_balance._num(r['annual']['balance_projected'])}"
             f"/{leave_balance._num(r['annual']['entitled'])} · Sick "
             f"{leave_balance._num(r['sick']['balance_projected'])}/"
             f"{leave_balance._num(r['sick']['entitled'])} · Special "
             f"{leave_balance._num(r['special']['balance_projected'])}")
        for c in r["special"]["expiring"]:
            s += f"\n⏰ Ngày bù lễ {c['name']} hết hạn {c['expiry']:%d/%m}"
        return s
    except Exception as e:  # noqa: BLE001
        log.warning("Số dư phép lỗi (%s).", e)
        return "Phép còn: (lỗi tính — xem log)"


async def cmd_retry_notes(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/retrynotes — xử lý lại tin bị giữ do AI lỗi (từng tin một).
    /retrynotes xem → liệt kê   •   /retrynotes bỏ → bỏ tin đầu (tự gõ lại)"""
    if not is_allowed(update): return
    state = state_mod.load_state()
    q = list(state.get("pending_notes") or [])
    arg = " ".join(context.args or []).strip().lower()
    if not q:
        await update.effective_message.reply_text("✅ Không có tin nào đang chờ.")
        return
    if arg in ("xem", "list"):
        await _reply_long(update, f"📥 {len(q)} TIN CHỜ XỬ LÝ (AI lỗi lúc nhắn):\n"
            + "\n".join(f"{i}. [{p['at'][5:16].replace('T', ' ')}] {p['text']}"
                        for i, p in enumerate(q, 1))
            + "\n\n/retrynotes → xử lý tin 1   •   /retrynotes bỏ → bỏ tin 1")
        return
    if arg in ("bỏ", "bo", "skip", "xóa", "xoa"):
        dropped = q.pop(0)
        state["pending_notes"] = q
        state_mod.save_state(state)
        audit("NOTE_PENDING_DROP", dropped["text"][:60])
        await update.effective_message.reply_text(
            f"Đã BỎ tin: “{dropped['text']}” (không ghi gì). Còn {len(q)} tin chờ.")
        return
    item = q.pop(0)
    state["pending_notes"] = q
    state_mod.save_state(state)
    ai_client.clear_rule_parser_mode()   # bro chủ động thử lại → cho AI 1 cơ hội
    await update.effective_message.reply_text(
        f"Đang xử lý lại (còn {len(q)} tin khác chờ):\n“{item['text']}”")
    _sd = item.get("sent_day")
    await _handle_note_action(update, state, item["text"],
                              sent_day=date.fromisoformat(_sd) if _sd else None)
    left = len(state_mod.load_state().get("pending_notes") or [])
    if left:
        await update.effective_message.reply_text(
            f"📥 Còn {left} tin chờ — nhắn /retrynotes để xử lý tin kế.")


async def cmd_leave_bal(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leavebal — số ngày phép còn lại (Annual / Sick / Special)."""
    if not is_allowed(update): return
    r = await asyncio.to_thread(leave_balance.compute_balance, config)
    await _reply_long(update, leave_balance.format_balance(r))


async def cmd_leave_log(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leavelog — lịch sử từng ngày nghỉ trong năm."""
    if not is_allowed(update): return
    r = await asyncio.to_thread(leave_balance.compute_balance, config)
    await _reply_long(update, leave_balance.format_log(r))


async def _updateleave_preview(update, state: dict, text: str) -> None:
    vals, errs = leave_balance.parse_update(text)
    if errs:
        state["conversation"] = {"awaiting": "update_leave_input"}
        state_mod.save_state(state)
        await _reply_long(update, "\n".join(f"⚠️ {e}" for e in errs)
                          + "\nNhập lại (vd: AL 10 SICK 14 SL 0), "
                          "hoặc 'hủy'.")
        return
    r = await asyncio.to_thread(leave_balance.compute_balance, config, state)
    today = date.today().strftime("%d/%m/%Y")
    if vals.get("reset"):
        body = ("Xóa HẾT mốc đã nhập tay → bot tự tính lại hoàn toàn từ "
                "file Excel đã gửi (Annual "
                f"{leave_balance._num(r['annual']['entitled'])}, Sick "
                f"{leave_balance._num(r['sick']['entitled'])}, Special theo lễ T7).")
    else:
        body = "\n".join(
            f"• {leave_balance.LABEL[k]}: "
            f"{leave_balance._num(r[k]['balance_confirmed'])} → "
            f"{leave_balance._num(v)} ngày (số dư HIỆN TẠI, đã tính mọi ngày nghỉ đang có)"
            for k, v in vals.items())
        body += ("\nTừ giờ, MỌI thay đổi nghỉ phép — kể cả sửa ngày CŨ bằng "
                 "/edittimesheet — đều được trừ/cộng vào con số này.")
    state["conversation"] = {"awaiting": "update_leave_confirm", "values": vals}
    state_mod.save_state(state)
    await _reply_long(update, "✏️ CẬP NHẬT NGÀY PHÉP:\n" + body
                      + "\n\nNhắn 'ok' để LƯU, nhắn gì khác để hủy.")


async def cmd_update_leave(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/updateleave — nhập tay số ngày phép còn lại (đặt mốc)."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    if context.args:
        await _updateleave_preview(update, state, " ".join(context.args))
        return
    r = await asyncio.to_thread(leave_balance.compute_balance, config, state)
    state["conversation"] = {"awaiting": "update_leave_input"}
    state_mod.save_state(state)
    cur = ", ".join(f"{k.upper() if k != 'annual' else 'AL'} "
                    f"{leave_balance._num(r[k]['balance_confirmed'])}"
                    for k in ("annual", "sick", "special"))
    await update.effective_message.reply_text(
        f"Số dư hiện tại: {cur.replace('SPECIAL', 'SL')}\n\n"
        "Nhắn số ngày CÒN LẠI muốn đặt (chỉ ghi loại cần sửa):\n"
        "  AL 10          → phép năm còn 10\n"
        "  SICK 14 SL 0   → nghỉ bệnh còn 14, nghỉ bù còn 0\n"
        "  AL 0           → hết phép năm\n"
        "  reset          → xóa mốc, để bot tự tính lại\n"
        "Nửa ngày ghi 9.5. Nhắn 'hủy' để thoát.")


_RESUMABLE = ("compose_confirm", "ts_mail_confirm", "resend_confirm")


async def _reshow_pending(update, conv: dict) -> None:
    """Hiện LẠI email đang chờ (sau khi đổi mail) với From/Bcc MỚI → 'ok'."""
    state = state_mod.load_state()
    state["conversation"] = conv
    state_mod.save_state(state)
    aw = conv.get("awaiting")
    if aw == "compose_confirm":
        await _reply_long(update, "📧 Email đang chờ — sẽ gửi bằng mail MỚI:\n\n"
                          + compose_email.format_preview(conv.get("email", {}), config))
        return
    manual = _MANUAL_BODY.get("body") if conv.get("manual") else None
    if aw == "ts_mail_confirm":
        prev = await asyncio.to_thread(orchestrator.prepare_send_preview, config,
                                       state, False, manual)
    else:
        prev = await asyncio.to_thread(orchestrator.prepare_resend_preview,
                                       conv.get("months") or [], config, state,
                                       bool(conv.get("force")), manual)
    if manual and prev.get("status") == "review":
        prev["preview"] = (prev["preview"]
                           .replace("NỘI DUNG EMAIL (y chang gửi sếp)",
                                    "NỘI DUNG EMAIL — BRO TỰ GÕ, gửi NGUYÊN VĂN")
                           .replace("✍️ Muốn tự viết nội dung email (nhắn thêm gì cho sếp): /manualmail",
                                    "✍️ /manualmail để gõ lại · trong lúc gõ nhắn 'hủy' để quay về email tự động"))
    if prev.get("status") == "review":
        await _reply_long(update, prev["preview"])
    else:
        state["conversation"] = None
        state_mod.save_state(state)
        await _reply_long(update, "\n".join(f"• {q}" for q in prev.get("questions", []))
                          or f"Không hiện lại được email ({prev.get('status')}).")


# Nội dung email bro TỰ GÕ (/manualmail) — CHỈ giữ trong BỘ NHỚ lúc bot chạy,
# không ghi state.json / notes / log. Gửi xong xóa. Bot khởi động lại → mất.
_MANUAL_BODY: dict = {}
_MANUAL_LOST_MSG = ("⚠️ Nội dung email bro tự gõ đã MẤT (bot vừa khởi động lại) — "
                    "CHƯA gửi gì. /manualmail để gõ lại, hoặc 'hủy' rồi làm lại "
                    "để gửi email tự động.")


def _manual_body_or_warn(conv: dict):
    """None = dùng email tự động; str = nội dung tự gõ; False = đã đánh dấu tự
    gõ nhưng nội dung đã mất (bot khởi động lại) → KHÔNG được gửi."""
    if not conv.get("manual"):
        return None
    return _MANUAL_BODY.get("body") or False


async def cmd_manual_mail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/manualmail — tự gõ 100% nội dung email timesheet / gởi lại."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    conv = state.get("conversation") or {}
    if conv.get("awaiting") == "manual_mail_body":
        conv = conv.get("back") or {}
    if conv.get("awaiting") not in ("ts_mail_confirm", "resend_confirm"):
        await update.effective_message.reply_text(
            "/manualmail chỉ dùng khi bot đang hiện EMAIL XEM TRƯỚC timesheet "
            "(thứ 6: 'ok' lần 1) hoặc GỞI LẠI. Làm tới bước đó rồi gõ /manualmail.")
        return
    state["conversation"] = {"awaiting": "manual_mail_body", "back": conv}
    state_mod.save_state(state)
    await update.effective_message.reply_text(
        f"✍️ Gõ TOÀN BỘ nội dung email (từ 'Hi {config.get('boss_name')}' tới chữ ký) trong 1 tin nhắn.\n"
        "• Bot gửi NGUYÊN VĂN 100% — không thêm, không sửa chữ nào.\n"
        "• Tiêu đề + file Excel đính kèm GIỮ NGUYÊN.\n"
        "• Không tự thêm ghi chú Special Leave → cần thì tự viết vào.\n"
        "• Nội dung chỉ nằm trong bộ nhớ, gửi xong là xóa.\n"
        "Nhắn 'hủy' để quay về email tự động.")


async def _start_resend(update, state: dict) -> None:
    """GỞI LẠI timesheet cho sếp (tháng vừa sửa, hoặc tháng gửi gần nhất):
    dựng email xem trước → chờ 'ok'. Dùng chung cho câu 'gởi lại' và lệnh
    /resend (25-Sep) — cùng 1 đoạn code, không lệch nhau."""
    # Ưu tiên gửi tháng VỪA SỬA (nếu có), rồi mới tới tháng last_sent
    edited = state.get("last_edited_months") or []
    last = state_mod.last_sent_date(state)
    if edited:
        months_to_send = edited
    elif last is not None:
        months_to_send = [last.strftime("%Y-%m")]
    else:
        await update.effective_message.reply_text(
            "Chưa từng gửi timesheet nên chưa có gì để gửi lại bro.")
        return
    await update.effective_message.reply_text(
        f"Đang soạn email gởi lại (tháng {', '.join(months_to_send)}) "
        "để bro xem trước…")
    prev = await asyncio.to_thread(
        orchestrator.prepare_resend_preview, months_to_send,
        config, state)
    if prev.get("status") != "review":
        if prev.get("status") == "need_info":
            state["conversation"] = {"awaiting": "resend_need_info",
                                     "months": months_to_send}
            state_mod.save_state(state)
            await _reply_long(update, "⚠️ CHƯA gởi lại — cần bro xem:\n"
                + "\n".join(f"• {q}" for q in prev.get("questions", []))
                + "\n━━━━━━━━━━━━━━━━━━\n👉 Sửa xong thì gõ /resend lần "
                "nữa · nhắn 'vẫn gởi' để BỎ QUA cảnh báo và xem trước email · "
                "'hủy' để thôi.")
            return
        await _reply_long(update, str(prev))
        return
    state["conversation"] = {"awaiting": "resend_confirm",
                             "months": months_to_send}
    state_mod.save_state(state)
    await _reply_long(update, prev["preview"])
    return


async def cmd_resend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resend — gởi lại timesheet cho sếp (y như nhắn 'gởi lại')."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    aw = (state.get("conversation") or {}).get("awaiting")
    if aw not in (None, "resend_need_info", "resend_confirm"):
        await update.effective_message.reply_text(
            "Đang dở 1 bước khác (bot đang chờ bro trả lời). Nhắn 'ok' để hoàn tất "
            "hoặc 'hủy' để bỏ bước đó, rồi gõ lại /resend.")
        return
    audit("CMD_RESEND", "/resend")
    await _start_resend(update, state)


async def cmd_personal_mail_on(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """/personalmailon — xin xác nhận rồi chuyển sang gửi bằng Gmail cá nhân."""
    if not is_allowed(update): return
    if not getattr(config, "gmail_ok", True):          # Gmail là TÙY CHỌN (02-Oct)
        await update.effective_message.reply_text(
            "⚠️ Chưa thiết lập Gmail cá nhân (" + config.gmail_problem + ").\n"
            "→ Bot VẪN gửi bằng MAIL CÔNG TY như bình thường.\n"
            "Muốn gửi bằng Gmail: điền GMAIL_ADDRESS + GMAIL_APP_PASSWORD trong "
            "config\\secrets.env (README Bước 7), khởi động lại bot rồi gõ lại /personalmailon.")
        return
    state = state_mod.load_state()
    if state.get("mail_mode") == "personal":
        await update.effective_message.reply_text(
            "Đang gửi bằng GMAIL CÁ NHÂN sẵn rồi. /personalmailoff để về "
            "mail công ty.")
        return
    # Có hạn 5 phút: tránh 'ok' duyệt nháp vài tiếng sau bị hiểu nhầm.
    # Email ĐANG CHỜ (vd vừa gửi lỗi bằng mail công ty) được GIỮ trong
    # "resume" → bật xong hiện lại để gửi bằng Gmail.
    prev = state.get("conversation") or {}
    state["conversation"] = {"awaiting": "personal_mail_confirm",
                             "at": datetime.now().isoformat(),
                             "resume": prev if prev.get("awaiting") in _RESUMABLE else None}
    state_mod.save_state(state)
    await update.effective_message.reply_text(
        "⚠️ Chuyển sang gửi bằng GMAIL CÁ NHÂN?\n"
        f"  From: {config.gmail_address}\n"
        f"  Bcc : {mailer.BCC_WHEN_PERSONAL or '(không)'}\n"
        "Áp dụng cho cả email timesheet lẫn email nghỉ phép.\n"
        "Nhắn 'ok' để BẬT, nhắn gì khác để giữ mail công ty.")


async def cmd_personal_mail_off(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """/personalmailoff — quay về mail công ty (mặc định), không cần hỏi."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    state["mail_mode"] = "company"
    conv = state.get("conversation") or {}
    if conv.get("awaiting") == "personal_mail_confirm":
        conv = conv.get("resume") or {}
        state["conversation"] = conv or None
    state_mod.save_state(state)
    if conv.get("awaiting") in _RESUMABLE:
        await update.effective_message.reply_text(
            "✅ Đã về MAIL CÔNG TY. Hiện lại email đang chờ:")
        await _reshow_pending(update, conv)
        return
    audit("MAIL_MODE", "company (/personalmailoff)")
    await update.effective_message.reply_text(
        f"✅ Gửi bằng MAIL CÔNG TY ({mailer.BCC_WHEN_PERSONAL}), "
        f"Bcc {mailer.BCC_WHEN_COMPANY or 'không'}.\n"
        "Áp dụng cho cả email timesheet lẫn email nghỉ phép.")


async def cmd_reset_mailts(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetmailts — Hủy review email TIMESHEET đang chờ gửi thứ 6.
    Clear trạng thái chờ, KHÔNG gửi mail, cho người dùng sửa lại timesheet."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    conv = state.get("conversation") or {}
    was = conv.get("awaiting") in ("ts_mail_confirm", "resend_confirm")
    # Hủy review email timesheet: giữ draft để sửa, chỉ bỏ trạng thái chờ gửi
    if was:
        state["conversation"] = None
        state_mod.save_state(state)
        audit("CMD_RESETMAILTS", "hủy review email timesheet")
        await update.effective_message.reply_text(
            "✅ Đã hủy gửi email timesheet. KHÔNG có mail nào được gửi.\n"
            "Bản nháp vẫn còn — sửa timesheet rồi /weeklyrun lại, hoặc "
            "/checkdraft xem lại.")
    else:
        await update.effective_message.reply_text(
            "Không có email timesheet nào đang chờ gửi.")


async def cmd_reset_mail(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetmail — Thoát khỏi trạng thái soạn email đang chờ.
    Clear email nháp tạm + reset về bình thường (như chưa soạn gì).
    Dùng khi lỡ /composemail rồi đổi ý, không muốn gửi nữa."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    conv = state.get("conversation") or {}
    was_composing = conv.get("awaiting") in (
        "compose_ai_request", "compose_manual_input", "compose_confirm")
    state["conversation"] = None
    state_mod.save_state(state)
    audit("CMD_RESETMAIL", f"was_composing={was_composing}")
    if was_composing:
        await update.effective_message.reply_text(
            "✅ Đã thoát chế độ soạn email. Xóa email nháp tạm.\n"
            "Giờ nhắn gì cũng được (ghi chú timesheet, lệnh khác...).")
    else:
        await update.effective_message.reply_text(
            "Không có email nháp nào đang chờ. Mọi thứ bình thường.")


async def cmd_compose_mail(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/composemail — Soạn email cho sếp bằng AI.
    Bot hỏi người dùng muốn gửi nội dung gì → AI soạn → xác nhận → gửi.
    Module phụ compose_email.py, tách biệt timesheet."""
    if not is_allowed(update): return
    audit("CMD_COMPOSEMAIL", "")
    state = state_mod.load_state()
    state["conversation"] = {"awaiting": "compose_ai_request"}
    state_mod.save_state(state)
    await update.effective_message.reply_text(
        f"✍️ Soạn email cho sếp {config.get('boss_name')} (dùng AI).\n\n"
        "Bro muốn gửi nội dung gì? Nhắn tóm tắt tiếng Việt, ví dụ:\n"
        "• \"xin nghỉ ngày 10/9 và 18 Sept\"\n"
        "• \"xin nghỉ thứ 6 này\"\n"
        "• \"nghỉ nửa ngày sáng 16/2, nửa ngày chiều 17/2\"\n"
        "• \"as communicated, đổi phép từ 24/9 sang 1/10\"")


async def cmd_compose_manual(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """/composemanual — Soạn email nhập TAY (KHÔNG gọi AI).
    người dùng tự nhập subject + body → xác nhận → gửi."""
    if not is_allowed(update): return
    audit("CMD_COMPOSEMANUAL", "")
    state = state_mod.load_state()
    state["conversation"] = {"awaiting": "compose_manual_input"}
    state_mod.save_state(state)
    await update.effective_message.reply_text(
        "✍️ Soạn email nhập tay (KHÔNG dùng AI).\n\n"
        "Nhập theo dạng:\n"
        "Subject: <tiêu đề>\n"
        "<nội dung email, nhiều dòng tùy ý>\n\n"
        "Ví dụ:\n"
        "Subject: Leave Request - 10 Sept\n"
        f"Hi {config.get('boss_name')}\n\n"
        "I'd like to take leave on 10 Sept.\n"
        "Thanks\n\n"
        "Regards\n"
        f"{config.get('signature_name')}")


async def cmd_clear_notes(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clearnotes — Xóa ghi chú thô (notes.jsonl) NHƯNG giữ parsed_days.
    Dùng để dọn dấu vết xóa/ghi chú lặp gây nhiễu AI. Cần xác nhận YES.
    Khác /resetnotes: /resetnotes xóa CẢ parsed_days, /clearnotes GIỮ."""
    if not is_allowed(update): return
    state = state_mod.load_state()
    n = 0
    if notes_store.NOTES_FILE.exists():
        n = sum(1 for l in notes_store.NOTES_FILE.read_text(
            encoding="utf-8").splitlines() if l.strip())
    if n == 0:
        await update.effective_message.reply_text(
            "notes.jsonl đã trống rồi bro, không cần xóa.")
        return
    n_parsed = len(daily_store.load_all())
    state["conversation"] = {"awaiting": "clear_notes_confirm"}
    state_mod.save_state(state)
    audit("CMD_CLEARNOTES_ASK", f"{n} dòng notes, {n_parsed} ngày parsed")
    await _reply_long(update,
        f"⚠️ Sắp xóa {n} dòng ghi chú thô (notes.jsonl).\n\n"
        f"✅ parsed_days.json ({n_parsed} ngày) sẽ GIỮ NGUYÊN — "
        f"Excel, summary, weeklyrun vẫn chạy bình thường.\n"
        f"📁 notes.jsonl sẽ được backup trước khi xóa.\n\n"
        f"Nhắn '{CLEAR_NOTES_CONFIRM}' để xác nhận, hoặc bất kỳ gì khác để hủy.")


async def cmd_check_excel(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """/checkexcel — Validate file Excel tháng hiện tại trước khi gửi.
    Kiểm tra: task name hợp lệ, không cột trống, tổng giờ khớp."""
    if not is_allowed(update): return
    audit("CMD_CHECKEXCEL", "")
    from datetime import date as _date
    month = _date.today().replace(day=1)
    try:
        errors = excel_writer.validate_excel_file(month, config)
    except Exception as e:
        await update.effective_message.reply_text(
            f"Lỗi đọc file Excel: {type(e).__name__}: {e}")
        return
    if not errors:
        await update.effective_message.reply_text(
            f"✅ File Excel tháng {month.strftime('%m/%Y')} hợp lệ — "
            "sẵn sàng gửi mail bro!")
    else:
        msg = (f"⚠️ File Excel tháng {month.strftime('%m/%Y')} có "
               f"{len(errors)} vấn đề:\n\n"
               + "\n".join(f"• {e}" for e in errors[:25]))
        if len(errors) > 25:
            msg += f"\n...và {len(errors)-25} vấn đề khác"
        await _reply_long(update, msg)


async def cmd_weekly_run(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """/weeklyrun — Chạy toàn bộ quy trình thứ 6: tạo Excel + gửi mail.
    Tương đương chạy weekly_run.py từ tay. Không cần AI nếu parsed_days đã đủ."""
    if not is_allowed(update): return
    audit("CMD_WEEKLYRUN", "manual trigger")
    await update.effective_message.reply_text(
        "Đang chốt tuần (soạn bản nháp — CHƯA gửi sếp)…")
    try:
        import weekly_run as _wr
        result = await asyncio.to_thread(_wr.run_once, config)
        status = result.get("status")

        if status == "sent":
            await update.effective_message.reply_text(
                f"✅ Gửi xong! {result.get('message','')}")

        elif status == "need_info":
            qs = result.get("questions", [])
            await _reply_long(update,
                f"⚠️ Còn {len(qs)} vấn đề cần giải quyết:\n"
                + "\n".join(f"• {q}" for q in qs)
                + "\n\nSửa xong nhắn /weeklyrun lại, hoặc /forcesendmail để bỏ qua.")

        elif status == "ready":
            # Báo cáo RÚT GỌN dạng control total (không in preview dài)
            summary = _summarize_draft_result(result, config)
            await update.effective_message.reply_text(summary)

        elif status == "already_sent":
            _sd = result.get("send_day", "")
            _t = date.today()
            if _t.weekday() <= 3:           # thứ 2–5: tuần này chưa tới hạn chốt
                _nf = _t + timedelta(days=4 - _t.weekday())
                _msg = (f"Timesheet tuần trước (thứ 6 {_sd[8:10]}/{_sd[5:7]}) đã gửi rồi. "
                        f"Tuần này (thứ 6 {_nf.strftime('%d/%m')}) CHƯA tới lúc chốt — "
                        "17:00 thứ 6 mình tự nhắc. Chốt sớm: nhắn \"gởi timesheet tới hôm nay\".")
            else:
                _msg = (f"Timesheet thứ 6 {_sd[8:10]}/{_sd[5:7]} đã gửi rồi bro. Sửa & gởi "
                        "lại: /edittimesheet → /resend.")
            await update.effective_message.reply_text(_msg)

        else:
            await update.effective_message.reply_text(
                f"Trạng thái: {status}")
    except Exception as e:
        log.exception("cmd_weekly_run lỗi")
        await update.effective_message.reply_text(
            f"Lỗi weekly run: {type(e).__name__}: {e}\nXem log để biết thêm.")


def _summarize_draft_result(result: dict, config) -> str:
    """Tóm tắt bản nháp dạng control total gọn cho Telegram.
    Thay vì in nguyên preview dài, chỉ hiện số liệu tổng hợp."""
    from datetime import date as _date
    send_day = result.get("send_day", "?")

    # Đọc parsed_days để tính control total
    data = daily_store.load_all()
    total_hours = 0.0
    total_rows = 0
    task_count: dict = {}
    day_count = 0
    for day_str, day_data in data.items():
        entries = day_data.get("entries", [])
        if not entries:
            continue
        day_count += 1
        for e in entries:
            h = float(e.get("hours") or 0)
            total_hours += h
            total_rows += 1
            t = e.get("task", "?")
            task_count[t] = task_count.get(t, 0) + h

    # Dòng phân loại theo task (giờ)
    task_lines = "\n".join(
        f"  • {t}: {h:g}h"
        for t, h in sorted(task_count.items(), key=lambda x: -x[1]))

    files = result.get("files", [])
    file_note = ""
    if files:
        import os as _os
        fname = _os.path.basename(str(files[0]))
        file_note = f"\n📄 Bản nháp: {fname}\n   (trong data\\preview — CHƯA gửi)"

    return (
        f"✅ BẢN NHÁP SẴN SÀNG — gửi ngày {send_day}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 CONTROL TOTAL:\n"
        f"  • Số ngày: {day_count}\n"
        f"  • Số dòng: {total_rows}\n"
        f"  • TỔNG GIỜ: {total_hours:g}h\n"
        f"\n📋 Theo loại task:\n{task_lines}\n"
        f"{file_note}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Nhắn 'ok' để CHỐT GỬI cho sếp, hoặc /checkdraft xem chi tiết."
    )


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    audit("NON_TEXT_MESSAGE", "")
    await update.effective_message.reply_text(
        "Mình chỉ nhận tin nhắn chữ thôi bro, gõ giúp mình nha.")


async def _auto_stop_watcher(app: Application):
    stop_str = config.get("bot_stop_time")
    if stop_str == "":
        log.info("bot_stop_time trống — bot không tự tắt theo giờ.")
        return
    hh, mm = (int(p) for p in stop_str.split(":"))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    log.info("Bot sẽ tự tắt lúc %s", target.strftime("%Y-%m-%d %H:%M"))
    await asyncio.sleep((target - datetime.now()).total_seconds())
    log.info("Tới giờ tắt (%s) — bot tự dừng.", stop_str)
    audit("BOT_AUTO_STOP", stop_str)
    app.stop_running()


async def _notify_holiday_missing(year: int):
    from telegram import Bot
    async with Bot(config.telegram_bot_token) as bot:
        await bot.send_message(
            chat_id=config.telegram_allowed_chat_id,
            text=f"Lưu ý bro: đã giữa tháng 12 mà mình vẫn chưa lấy "
                f"được lịch nghỉ lễ Singapore năm {year} từ MOM (chắc "
                "họ chưa đăng, hoặc mạng trục trặc). Mình sẽ tự thử "
                "lại mỗi lần khởi động. Nếu qua Tết mà vẫn chưa có, "
                "nhắn Claude kiểm tra giúp bro nhé.")


_APP = None                      # Application đang chạy (để tự tắt sau khi gửi)
AUTO_STOP_AFTER_SEND_SEC = 60    # gửi xong timesheet tuần (T6–CN) → tắt sau 1 phút
_STOP_TASKS: set = set()


async def _after_weekly_sent(update, result: dict) -> None:
    """(02-Oct) Gửi THÀNH CÔNG timesheet của TUẦN NÀY vào T6 / T7 / CN → chúc
    cuối tuần + bot tự tắt sau 1 phút (không chạy vô ích tới 23:59).
    KHÔNG tắt khi: gởi lại (/resend) · chốt sớm T2–T5 · gửi muộn tuần trước
    từ thứ 2 tuần sau."""
    if result.get("kind") != "weekly" or _APP is None:
        return
    today = date.today()
    if today.weekday() < 4:                       # T2–T5
        return
    this_fri = today - timedelta(days=today.weekday() - 4)
    if result.get("send_day") != this_fri.isoformat():
        return
    app = _APP
    at = datetime.now() + timedelta(seconds=AUTO_STOP_AFTER_SEND_SEC)
    await update.effective_message.reply_text(
        f"✅ Timesheet tuần {this_fri:%d/%m} đã gửi thành công.\n"
        "🎉 Chúc bro một cuối tuần vui vẻ bên gia đình!\n"
        f"🤖 Bot tự tắt lúc {at:%H:%M} sau khi gửi timesheet tuần {this_fri:%d/%m} "
        "thành công. Cần dùng lại thì nhấp đúp start_bot.vbs (Mac: start_bot.command) "
        "— hoặc bot tự bật lúc 16:00 hôm sau.")
    log.info("Gửi xong timesheet tuần %s — bot tự tắt lúc %s.", this_fri, at.strftime("%H:%M"))

    async def _stop():
        await asyncio.sleep(AUTO_STOP_AFTER_SEND_SEC)
        audit("BOT_AUTO_STOP_AFTER_SEND", f"tuần {this_fri.isoformat()}")
        log.info("Bot tự tắt (đã gửi timesheet tuần %s).", this_fri)
        app.stop_running()
    t = asyncio.create_task(_stop())
    _STOP_TASKS.add(t)
    t.add_done_callback(_STOP_TASKS.discard)


async def _post_init(app: Application):
    global _APP
    _APP = app
    app.create_task(_auto_stop_watcher(app))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if isinstance(err, _TG_NET_ERRORS):
        # Thư viện Telegram tự kết nối lại → chỉ 1 dòng cảnh báo
        log.warning("Mất kết nối Telegram (%s), đang thử lại.", type(err).__name__)
        return
    log.error("Lỗi chưa bắt: %s: %s", type(err).__name__, err, exc_info=err)
    audit("ERROR", f"{type(err).__name__}: {err}")


def main():
    global config

    if not acquire_single_instance_lock():
        log.warning("Đã có 1 bot khác đang chạy trên máy này — thoát.")
        print("Đã có 1 bot khác đang chạy. Cửa sổ này sẽ tự thoát.")
        sys.exit(0)

    try:
        config = load_config()
    except ConfigError as e:
        log.critical("Lỗi cấu hình: %s", e)
        print("LỖI CẤU HÌNH:\n" + str(e))
        sys.exit(1)

    # Timeout rộng hơn + retry khi mạng chậm/chập chờn lúc khởi động.
    # Trước đây mặc định 5s, retry 0 lần → mạng lag 1 chút là BOT SẬP
    # (lỗi "Network Retry Loop Bootstrap Timed out"). Nay:
    #   connect/read/write 20s, get_updates 30s.
    app = (Application.builder()
           .token(config.telegram_bot_token)
           .post_init(_post_init)
           .connect_timeout(20.0)
           .read_timeout(20.0)
           .write_timeout(20.0)
           .pool_timeout(20.0)
           .get_updates_read_timeout(30.0)
           .build())
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    # Lệnh reset phải đăng ký CommandHandler riêng — Telegram parse /xxx
    # thành command entity, không vào MessageHandler nếu không đăng ký.
    # Lưu ý: gạch ngang trong tên lệnh Telegram không hỗ trợ -> dùng
    # tên không dấu gạch ngang (resetnotes, resetstatus) là tên chính,
    # tên có gạch ngang thêm vào MessageHandler để bắt luôn cả 2 dạng.
    async def _cmd_reset_status(update, context):
        await handle_text(update, context)
    async def _cmd_reset_notes(update, context):
        await handle_text(update, context)
    app.add_handler(CommandHandler("resetstatus",  _cmd_reset_status))
    app.add_handler(CommandHandler("resetnotes",   _cmd_reset_notes))
    app.add_handler(CommandHandler("summary",        cmd_summary))
    app.add_handler(CommandHandler("summaryweek",    cmd_summary_week))
    app.add_handler(CommandHandler("checknotes",     cmd_validate_notes))
    app.add_handler(CommandHandler("createdraft",    cmd_create_draft))
    app.add_handler(CommandHandler("forcedraft",     cmd_force_draft))
    app.add_handler(CommandHandler("checkdraft",     cmd_check_draft))
    app.add_handler(CommandHandler("sendmail",       cmd_send_mail))
    app.add_handler(CommandHandler("forcesendmail",  cmd_force_send_mail))
    app.add_handler(CommandHandler("weeklyrun",      cmd_weekly_run))
    app.add_handler(CommandHandler("deletedraft",    cmd_delete_draft))
    app.add_handler(CommandHandler("checkexcel",     cmd_check_excel))
    app.add_handler(CommandHandler("clearnotes",     cmd_clear_notes))
    app.add_handler(CommandHandler("composemail",    cmd_compose_mail))
    app.add_handler(CommandHandler("composemanual",  cmd_compose_manual))
    app.add_handler(CommandHandler("resetmail",      cmd_reset_mail))
    app.add_handler(CommandHandler("resetmailts",    cmd_reset_mailts))
    app.add_handler(CommandHandler("personalmailon", cmd_personal_mail_on))
    app.add_handler(CommandHandler("personalmailoff", cmd_personal_mail_off))
    app.add_handler(CommandHandler("leavebal",       cmd_leave_bal))
    app.add_handler(CommandHandler("manualmail",     cmd_manual_mail))
    app.add_handler(CommandHandler("resend",         cmd_resend))
    app.add_handler(CommandHandler("retrynotes",     cmd_retry_notes))
    app.add_handler(CommandHandler("leavelog",       cmd_leave_log))
    app.add_handler(CommandHandler("updateleave",    cmd_update_leave))
    app.add_handler(CommandHandler("edittimesheet",  cmd_edit_timesheet))
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND,
        handle_text))
    app.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & ~filters.TEXT, handle_other))
    app.add_error_handler(on_error)

    state_mod.clear_stale_lock_at_startup()

    try:
        import housekeeping
        housekeeping.run()
    except Exception:  # noqa: BLE001 — dọn dẹp hỏng không được chặn bot
        log.exception("Housekeeping lỗi — bỏ qua, bot vẫn chạy.")

    try:
        import sg_holidays
        holiday_status = sg_holidays.ensure_next_year_cached(config)
        if not holiday_status["ok"]:
            log.warning("CẢNH BÁO: chưa có lịch nghỉ lễ năm %s — "
                       "cần trước 1-Jan để tính lễ đúng.",
                       holiday_status["year"])
    except Exception:  # noqa: BLE001 — không được chặn bot khởi động
        log.exception("Kiểm tra lịch nghỉ lễ năm sau lỗi — bỏ qua.")
        holiday_status = None

    if holiday_status and not holiday_status["ok"] and date.today().day >= 15:
        try:
            asyncio.run(_notify_holiday_missing(holiday_status["year"]))
        except Exception:
            log.exception("Không nhắn được cảnh báo thiếu lịch lễ.")

    log.info("=" * 46)
    log.info("BOT TIMESHEET v2 KHỞI ĐỘNG — phục vụ chat_id %s",
             config.telegram_allowed_chat_id)
    log.info("=" * 46)
    audit("BOT_START", "v2")

    # RETRY khi lỗi MẠNG lúc khởi động (TimedOut/NetworkError). Trước đây
    # mạng lag 1 chút lúc bootstrap là bot tắt luôn. Nay thử lại tối đa
    # 5 lần, chờ tăng dần. Lỗi KHÁC (code/token) vẫn raise ngay.
    from telegram.error import TimedOut, NetworkError
    import time as _time
    max_net_retry = 5
    for attempt in range(1, max_net_retry + 1):
        try:
            app.run_polling(allowed_updates=Update.ALL_TYPES,
                            drop_pending_updates=False)
            break  # run_polling thoát bình thường (Ctrl-C / tự tắt) → xong
        except (TimedOut, NetworkError) as e:
            wait = min(attempt * 10, 60)
            log.warning("Lỗi mạng lúc khởi động (%s) — lần %d/%d, "
                        "chờ %ds rồi thử lại.",
                        type(e).__name__, attempt, max_net_retry, wait)
            audit("BOT_NET_RETRY", f"{type(e).__name__} lần {attempt}")
            if attempt >= max_net_retry:
                log.critical("BOT SẬP sau %d lần thử mạng: %s",
                             max_net_retry, e, exc_info=True)
                audit("BOT_CRASH", f"Mạng: {type(e).__name__}: {e}")
                raise
            _time.sleep(wait)
        except Exception as e:  # noqa: BLE001 — QUY TẮC DI THƯ
            log.critical("BOT SẬP: %s: %s", type(e).__name__, e, exc_info=True)
            audit("BOT_CRASH", f"{type(e).__name__}: {e}")
            raise
    audit("BOT_STOP", "")
    log.info("Bot đã dừng.")


if __name__ == "__main__":
    main()
