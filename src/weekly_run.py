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


AUTO_RETRY_BUDGET_SEC = 40       # không bắt đầu tin mới sau ~40s (bot chờ khóa tối đa 75s)


def auto_retry_pending(config, state: dict, send_day: date) -> dict:
    """(11-Oct-2026) 17:00 thứ 6 — AI đã ổn lại → TỰ xử lý lại hàng chờ
    pending_notes (tin AI lỗi lúc nhắn, luật dự phòng cũng không hiểu).

    RẤT THẬN TRỌNG — chỉ TỰ GHI khi TẤT CẢ đúng:
      • AI đọc ra việc timesheet, không lỗi, không cần xác nhận
      • MỌI ngày đích còn TRỐNG trong parsed_days (không bao giờ ghi đè / sửa
        dữ liệu đã có — kể cả dữ liệu bro tự nhắn lại sau đó)
      • không đụng ngày ĐÃ GỬI (theo last_sent lẫn file Excel tháng) → chạy tự
        động KHÔNG BAO GIỜ ghi file Excel
    Ngày hiểu theo NGÀY NHẮN gốc của tin. Gặp tin đầu tiên không tự ghi được
    (hoặc AI lỗi / lỗi lạ / quá giờ) → DỪNG, giữ nguyên tin đó và mọi tin sau
    theo đúng thứ tự cho người dùng tự /retrynotes.
    Trả {"done": [dòng đã ghi], "kept": [(câu, lý do)]}."""
    import time
    import ai_client
    import daily_store
    import note_action
    import state as state_mod

    out = {"done": [], "kept": []}
    try:
        q = list(state.get("pending_notes") or [])
        if not q or state_mod.already_sent(state, send_day):
            return out
        conv = state.get("conversation") or {}
        if isinstance(conv, dict) and conv.get("awaiting") == "past_edit_confirm":
            return out                     # đang có câu hỏi treo → để người dùng trả lời
        ai_client.clear_rule_parser_mode()  # như /retrynotes: cho AI 1 cơ hội
        last = state_mod.last_sent_date(state)
        t0 = time.monotonic()
        for item in q:
            text = item.get("text") or ""
            if time.monotonic() - t0 > AUTO_RETRY_BUDGET_SEC:
                out["kept"].append((text, "hết giờ tự xử lý — mình dừng ở đây"))
                break
            try:
                _sd = item.get("sent_day")
                sd = date.fromisoformat(_sd) if _sd else None
                acts, not_act = note_action.parse_actions(text, config, None, sd)
            except ai_client.AIError as e:
                log.warning("Tự xử lý hàng chờ: AI lỗi (%s) — dừng.", e)
                out["kept"].append((text, "AI vẫn lỗi khi đọc lại — mình dừng, chưa thử các tin sau"))
                break
            except Exception as e:  # noqa: BLE001 — AI trả dữ liệu lạ
                log.warning("Tự xử lý hàng chờ: dữ liệu lạ (%s) — dừng.", e)
                out["kept"].append((text, "AI trả dữ liệu lạ — mình dừng, chưa thử các tin sau"))
                break
            if not_act or not acts:
                out["kept"].append((text, "AI không thấy việc timesheet nào trong câu này"))
                break
            pd_now = daily_store.load_all()
            acts = note_action.validate_actions(acts, pd_now, config)
            days = sorted({a.day for a in acts if a.day})
            why = ""
            if any(a.error for a in acts):
                why = "AI đọc ra nhưng có lỗi: " + "; ".join(a.error for a in acts if a.error)
            elif not days or any(a.day is None for a in acts):
                why = "không rõ ngày nào"
            elif (last is not None and any(d <= last for d in days)) or \
                    note_action._sent_days_for(days, state, config):
                why = "đụng ngày ĐÃ GỬI sếp (sửa bằng /edittimesheet)"
            elif any(d.isoformat() in pd_now for d in days):
                why = "ngày đó ĐÃ CÓ dữ liệu — cần bro xem & xác nhận"
            elif any(a.needs_confirm for a in acts):
                why = "cần bro xác nhận"
            if why:
                out["kept"].append((text, why))
                break
            res = note_action.persist_actions(acts, config, state, False)
            # Rút tin khỏi hàng chờ NGAY sau khi ghi (lỡ lỗi giữa chừng cũng
            # không ghi trùng lần sau)
            state["pending_notes"] = [p for p in state.get("pending_notes") or []
                                      if p is not item]
            state_mod.save_state(state)
            audit("NOTE_PENDING_AUTO", text[:60])
            for d, ents in res.get("written_days", []):
                if ents is None:
                    out["done"].append(f"  • {note_action._dmy(d)}: đã xóa")
                else:
                    out["done"].append(f"  • {note_action._dmy(d)}: " + ", ".join(
                        f"{x.get('task')} {float(x.get('hours') or 0):g}h" for x in ents))
    except Exception as e:  # noqa: BLE001 — không được làm sập lượt chạy thứ 6
        log.exception("Tự xử lý hàng chờ lỗi bất ngờ (%s) — bỏ qua.", e)
    return out


def _confirm_preview_text(state: dict) -> str:
    """Bản xem trước GHI/SỬA đang chờ 'ok' (để tin 17:00 hiện lại). Lỗi → ""."""
    try:
        import note_action
        acts = []
        for x in (state.get("conversation") or {}).get("note_actions") or []:
            acts.append(note_action.Action(
                type=x["type"],
                day=date.fromisoformat(x["day"]) if x.get("day") else None,
                tasks=x.get("tasks", []),
                copy_from=date.fromisoformat(x["copy_from"]) if x.get("copy_from") else None,
                needs_confirm=x.get("needs_confirm", False),
                confirm_msg=x.get("confirm_msg", ""), error=x.get("error", ""),
                warning=x.get("warning", "")))
        return note_action.format_preview(acts) if acts else ""
    except Exception as e:  # noqa: BLE001
        log.warning("Không dựng lại được bản xem trước (%s)", e)
        return ""


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
        # (11-Oct) AI đã ổn → tự xử lý lại tin chờ trước khi soạn nháp
        auto = auto_retry_pending(config, state, send_day)
        state = state_mod.load_state()
        result = orchestrator.prepare_draft(config, state, send_day=send_day)

    # ĐÃ nhả khóa state (bot khởi động sẽ dọn file khóa → phải bật SAU khóa).
    # Bot phải CHẠY để nhận 'ok' / lệnh sau tin nhắn này.
    bot_note = _ensure_bot_running()

    auto_note = ""
    if auto.get("done"):
        auto_note = ("🔁 AI đã ổn lại → mình TỰ xử lý các tin chờ (AI lỗi lúc bro "
                     "nhắn) và đã ghi:\n" + "\n".join(auto["done"]) + "\n\n")

    def _notify(text, cfg, files=None):
        orchestrator.notify(auto_note + text + bot_note, cfg, files=files)

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

    if result["status"] == "need_info" and result.get("source") == "pending_confirm":
        questions = "\n".join(f"• {q}" for q in result["questions"])
        pv = _confirm_preview_text(state)
        _notify(f"Tới giờ chốt timesheet (thứ 6 {send_day.strftime('%d/%m')}) "
                f"nhưng bro còn 1 câu hỏi CHƯA trả lời:\n{questions}"
                + (f"\n\nBẢN XEM TRƯỚC ĐANG CHỜ 'ok':\n{pv}" if pv else ""), config)
        return

    if result["status"] == "need_info" and result.get("source") == "pending_notes":
        questions = "\n".join(f"• {q}" for q in result["questions"])
        why = "\n".join(f"  – “{t}”: {r}" for t, r in auto.get("kept") or [])
        _notify(
            f"Tới giờ chốt timesheet (thứ 6 {send_day.strftime('%d/%m')}) "
            f"nhưng còn tin nhắn CHƯA xử lý được nè bro:\n{questions}\n"
            + (f"\nLý do mình chưa tự xử lý:\n{why}\n" if why else "")
            + "\nNhắn /retrynotes để xử lý từng tin (xong tin nào mình báo tin đó). "
            "Hết tin chờ thì gõ /weeklyrun để mình soạn bản nháp.", config)
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
