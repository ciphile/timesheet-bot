"""
weekly_run.py — Entry #2: job thứ 6 (Task Scheduler gọi 17:00).

Vỏ mỏng quanh orchestrator: soạn nháp cho thứ 6 của tuần hiện tại rồi
nhắn người dùng qua Telegram (bản preview để duyệt, hoặc danh sách câu hỏi
nếu thiếu dữ liệu). KHÔNG BAO GIỜ tự gửi mail — cổng review nằm ở
bot.py, chỉ mở khi người dùng nhắn "ok".

Chạy bù thứ 7/CN (laptop tắt tối thứ 6): send_day vẫn là THỨ 6 của
tuần đó, không phải hôm nay.

Tuân QUY TẮC DI THƯ (PROJECT.md mục 13): mọi cú sập đều để lại
nguyên nhân trong log + audit trước khi chết.

Chạy tay để test:  python weekly_run.py (trong thư mục src)
"""

import sys
from datetime import date, timedelta

from config_loader import ConfigError, load_config
from log_setup import get_logger
from audit_log import audit

log = get_logger("weekly_run")


def effective_friday(today: date) -> date:
    """Thứ 6 của kỳ này: hôm nay nếu là thứ 6, không thì thứ 6 GẦN
    NHẤT TRƯỚC ĐÓ (chạy bù cuối tuần vẫn chốt sổ đúng thứ 6)."""
    return today - timedelta(days=(today.weekday() - 4) % 7)


def run_once(config) -> dict:
    """Chạy 1 lần weekly run và trả dict kết quả.
    Dùng bởi /weeklyrun trong bot.py."""
    from datetime import date
    import state as state_mod
    import orchestrator

    today = date.today()
    days_since_fri = (today.weekday() - 4) % 7
    send_day = today - __import__("datetime").timedelta(days=days_since_fri)
    state = state_mod.load_state()
    return orchestrator.prepare_draft(config, state, send_day=send_day)


BOT_PORT = 47391                       # = SINGLE_INSTANCE_PORT trong bot.py
BOT_TASK_WINDOWS = "Timesheet Bot"     # lịch Task Scheduler do CAI_DAT.bat tạo
BOT_LABEL_MAC = "com.timesheet.bot"    # lịch launchd do tao_lich_mac.sh tạo


def _bot_running() -> bool:
    """bot.py giữ cổng 47391 suốt lúc chạy → chiếm được cổng = bot đang TẮT."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", BOT_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _ensure_bot_running() -> str:
    """Tin nhắn chốt tuần cần bot.py ĐANG CHẠY để nhận 'ok' / lệnh. Bot tắt →
    BẬT: Windows chạy lịch "Timesheet Bot" (dự phòng start_bot.vbs) · Mac chạy
    lịch launchd com.timesheet.bot (dự phòng chạy thẳng python). Trả câu báo
    thêm vào tin nhắn ('' nếu bot vốn đang chạy)."""
    import os
    import subprocess
    import time
    from pathlib import Path
    if _bot_running():
        return ""
    log.warning("bot.py đang TẮT — weekly_run bật lại để người dùng trả lời được.")
    audit("WEEKLY_START_BOT", "bot đang tắt")
    here = Path(__file__).resolve().parent                     # thư mục src
    try:
        if sys.platform == "win32":
            ok = False
            try:
                r = subprocess.run(["schtasks", "/Run", "/TN", BOT_TASK_WINDOWS],
                                   capture_output=True, timeout=20)
                ok = r.returncode == 0
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                vbs = here.parent / "start_bot.vbs"
                try:     # tách khỏi lượt chạy weekly (Task Scheduler) nếu được
                    subprocess.Popen(["wscript.exe", str(vbs)], creationflags=0x01000000)
                except OSError:
                    subprocess.Popen(["wscript.exe", str(vbs)])
        else:
            ok = False
            if sys.platform == "darwin":
                try:
                    r = subprocess.run(["launchctl", "kickstart",
                                        f"gui/{os.getuid()}/{BOT_LABEL_MAC}"],
                                       capture_output=True, timeout=20)
                    ok = r.returncode == 0
                except Exception:  # noqa: BLE001
                    ok = False
            if not ok:
                subprocess.Popen([sys.executable, str(here / "bot.py")], cwd=str(here),
                                 start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        log.error("Không bật được bot: %s", e)
    for _ in range(60):                    # chờ tối đa ~30 giây bot khởi động
        if _bot_running():
            log.info("Đã bật lại bot.")
            return "\n\n🤖 (Bot đang tắt → mình đã BẬT lại, bro trả lời bình thường nhé.)"
        time.sleep(0.5)
    audit("WEEKLY_START_BOT_FAIL", "")
    return ("\n\n⚠️ Bot đang TẮT và mình chưa bật lại được → nhấp đúp start_bot.vbs "
            "(Mac: start_bot.command) trong thư mục timesheet rồi mới trả lời nhé.")


def main():
    import orchestrator
    import state as state_mod

    config = load_config()
    send_day = effective_friday(date.today())
    log.info("Weekly run: hôm nay %s, chốt sổ cho thứ 6 %s.",
             date.today(), send_day)
    audit("WEEKLY_RUN_START", send_day.isoformat())

    # QUAN TRỌNG: bot.py chạy nền cả ngày và có thể đang xử lý 1 tin
    # nhắn của người dùng đúng lúc job này bật lúc 17:00. state_lock() giữ
    # cả lượt (load -> prepare_draft -> notify) làm MỘT KHỐI, để 2
    # tiến trình không đụng nhau (không thì bản nháp job này vừa lưu
    # có thể bị 1 tin nhắn đến cùng lúc ghi đè mất — xem state.py).
    with state_mod.state_lock() as got_lock:
        if not got_lock:
            # Bot đang giữ khóa quá lâu (hiếm). Job thứ 6 KHÔNG chạy
            # liều: thà báo người dùng chạy lại bằng tay còn hơn ghi đè
            # chồng lên việc bot đang làm dở.
            log.error("Không lấy được khóa state — bỏ lượt chạy này.")
            audit("WEEKLY_RUN_BUSY", send_day.isoformat())
            orchestrator.notify(
                "Tới giờ chốt timesheet mà bot đang bận xử lý việc khác "
                "nên mình chưa soạn được. Bro chờ 1-2 phút rồi chạy tay "
                "giúp mình: python weekly_run.py (trong thư mục src)",
                config)
            return
        state = state_mod.load_state()
        result = orchestrator.prepare_draft(config, state, send_day=send_day)

    # ĐÃ nhả khóa state (bot khởi động sẽ dọn file khóa → phải bật SAU khóa).
    # Bot phải CHẠY để nhận 'ok' / lệnh sau tin nhắn này.
    bot_note = _ensure_bot_running()

    def _notify(text, cfg, files=None):
        orchestrator.notify(text + bot_note, cfg, files=files)

    if result["status"] == "already_sent":
        log.info("Tuần %s đã gửi rồi — không làm gì.", send_day)
        today = date.today()
        if today.weekday() <= 3:            # thứ 2–5: tuần này chưa tới hạn chốt
            next_fri = today + timedelta(days=4 - today.weekday())
            _notify(
                f"Timesheet tuần trước (thứ 6 {send_day.strftime('%d/%m')}) đã gửi "
                f"rồi nha bro. Tuần này (thứ 6 {next_fri.strftime('%d/%m')}) CHƯA tới "
                "lúc chốt — 17:00 thứ 6 mình tự nhắc. Muốn chốt sớm (vd mai nghỉ) "
                "thì nhắn \"gởi timesheet tới hôm nay\".", config)
        else:
            _notify(
                f"Timesheet thứ 6 {send_day.strftime('%d/%m')} đã gửi trước "
                "đó rồi nha bro, tuần này khỏe.", config)
        return

    if result["status"] == "need_info":
        questions = "\n".join(f"• {q}" for q in result["questions"])
        _notify(
            f"Tới giờ chốt timesheet (thứ 6 {send_day.strftime('%d/%m')}) "
            f"mà còn thiếu nè bro:\n{questions}\n\n"
            "Bro điền bổ sung giúp mình (nhắn như ghi chú bình thường, vd "
            "\"thứ 6 làm SDF PACSGASIA-4137\"). Điền xong thì gõ /weeklyrun "
            "(hoặc nhắn \"gởi timesheet tới hôm nay\") để mình soạn bản nháp.\n"
            "Thà gửi trễ còn hơn gửi thiếu!", config)
        return

    # status == "ready"
    hold_note = ("\n(Bro đang để chế độ KHOAN GỞI — mình giữ tới khi "
                 "bro ok nhé.)" if result.get("hold") else "")
    _notify(
        result["preview"]
        + "\n\nFile Excel xem trước gửi kèm bên dưới. "
        + "Ưng thì nhắn \"ok\" là mình gửi sếp; muốn sửa thì nói tự "
        + "nhiên (vd: \"thứ 5 đổi thành nghỉ phép\")." + hold_note,
        config, files=result.get("files"))


if __name__ == "__main__":
    try:
        main()
    except ConfigError as e:
        log.critical("Lỗi cấu hình: %s", e)
        print("LỖI CẤU HÌNH:\n" + str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 — QUY TẮC DI THƯ
        log.critical("WEEKLY RUN SẬP: %s: %s",
                     type(e).__name__, e, exc_info=True)
        audit("WEEKLY_RUN_CRASH", f"{type(e).__name__}: {e}")
        try:
            import orchestrator
            # Gửi NGUYÊN VĂN thông báo lỗi (các lớp lỗi tự viết đều
            # mang sẵn hướng dẫn hành động được, vd AIError nay còn
            # liệt kê luôn model nào đang dùng được). Trước đây chỉ
            # gửi TÊN loại lỗi -> người dùng phải mò log mới biết làm gì.
            orchestrator.notify(
                "Job thứ 6 bị lỗi rồi bro, chưa soạn được timesheet.\n\n"
                f"{type(e).__name__}: {str(e)[:900]}\n\n"
                "Sửa xong chạy lại: python weekly_run.py (trong thư mục src)",
                load_config())
        except Exception:
            log.exception("Không nhắn được Telegram báo lỗi.")
        raise
