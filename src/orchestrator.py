"""
orchestrator.py — Người dàn trận: nối pipeline + validator + excel +
mailer + state thành 3 nghiệp vụ lớn, dùng chung cho weekly_run.py
(chạy lịch thứ 6) và bot.py (người dùng ra lệnh):

1. prepare_draft(send_day)   : soạn BẢN NHÁP kỳ báo cáo
   - đủ dữ liệu  -> lưu draft vào state + preview text + file preview
   - thiếu       -> danh sách câu hỏi tiếng Việt (bot đi hỏi), KHÔNG
                    có gì được ghi vào file thật
2. apply_edit(user_text)     : sửa bản nháp theo lệnh tự nhiên
   - AI trả THAO TÁC theo NGÀY (set_day/delete_day) — tái dùng đúng
     bộ máy postprocess đã test, code thi hành, AI không đụng file
3. finalize_and_send()       : người dùng đã "ok" -> ghi file tháng thật
   (merge phần ngoài kỳ + draft), tạo bản giao, soạn mail (kèm câu
   Special Leave nếu có), GỬI, đánh dấu đã gửi.

Kèm notify(): gửi tin nhắn/file qua Telegram theo kiểu đồng bộ, cho
weekly_run dùng (bot.py có ngữ cảnh async riêng nên tự gửi).
"""

import asyncio
import json
from datetime import date, timedelta

import ai_client
import daily_store
import excel_writer
import mailer
import notes_store
import pipeline
import sg_holidays
import state as state_mod
import validator
from config_loader import DATA_DIR
from log_setup import get_logger
from audit_log import audit

log = get_logger("orchestrator")

PREVIEW_DIR = DATA_DIR / "preview"
TELEGRAM_CHUNK = 3500          # Telegram giới hạn ~4096 ký tự/tin


class OrchestratorError(Exception):
    """Lỗi nghiệp vụ dàn trận. Thông báo là tiếng Việt."""


# ---------------------------------------------------------------------
# 1) SOẠN BẢN NHÁP
# ---------------------------------------------------------------------

def prepare_draft(config, state: dict = None, force: bool = False,
                  send_day: date = None) -> dict:
    """Soạn bản nháp Excel từ parsed_days.
    Trả dict:
    {"status": "already_sent"} |
    {"status": "need_info", "questions": [..]} |
    {"status": "ready", "preview": str, "files": [Path], "hold": bool}

    Tham số:
    - config: bắt buộc
    - state: nếu None → tự load_state()
    - force: True → bỏ qua validation
    - send_day: None → tự tính thứ 6 gần nhất
    """
    if state is None:
        state = state_mod.load_state()
    if send_day is None:
        today = date.today()
        days_since_fri = (today.weekday() - 4) % 7
        send_day = today - timedelta(days=days_since_fri)
    if state_mod.already_sent(state, send_day):
        return {"status": "already_sent", "send_day": send_day.isoformat()}

    _pq = _pending_notes_block(state, force)
    if _pq:
        return {**_pq, "send_day": send_day.isoformat()}

    period = pipeline.compute_period(send_day, state, config)

    # BẢO VỆ: kỳ HOÀN TOÀN TRỐNG (không ngày làm việc, không ngày lễ)
    # — xảy ra khi người dùng lỡ gọi "gởi timesheet" vào cuối tuần NGAY SAU
    # khi đã gửi thứ 6 (vd last_sent=thứ 6, hôm nay=thứ 7 liền kề).
    # KHÔNG được coi đây là draft "ready" — nếu không chặn, validator
    # thấy expected_days=[] nên "sạch" ngay lập tức (không gì để
    # thiếu), và hệ thống sẽ sẵn sàng GỬI EMAIL RỖNG (0 tháng, 0 file
    # đính kèm) cho sếp nếu người dùng lỡ tay gõ "ok".
    if not period["expected_days"] and not period["ph_map"]:
        return {"status": "need_info", "send_day": send_day.isoformat(),
                "questions": [
                    f"Kỳ từ {period['start'].strftime('%d/%m')} tới "
                    f"{period['end'].strftime('%d/%m')} không có ngày "
                    "làm việc nào cần báo cáo (có thể bro gọi lệnh nhầm "
                    "ngày, hoặc timesheet mới gửi hôm qua/hôm nay rồi). "
                    "Không có gì để gửi cả."]}

    # CHECKPOINT: validate CẤU TRÚC parsed_days TRƯỚC khi tạo bản nháp.
    # Bắt lỗi parse sai (date lệch key, tổng ≠ 8h, task trùng, giờ phi
    # lý) — chặn tạo nháp từ dữ liệu hỏng. force=True vẫn cảnh báo nhưng
    # cho qua.
    _hpd = config.get("hours_per_day") or 8
    _struct_errs = validator.validate_parsed_structure(
        daily_store.load_all(), _hpd)
    if _struct_errs and not force:
        return {"status": "need_info", "send_day": send_day.isoformat(),
                "questions": [
                    "parsed_days có lỗi cấu trúc — sửa trước khi tạo nháp:",
                    *_struct_errs,
                    "Dùng /forcedraft nếu muốn bỏ qua (KHÔNG khuyến khích)."]}
    elif _struct_errs:
        log.warning("prepare_draft force=True: bỏ qua %d lỗi cấu trúc "
                    "parsed_days", len(_struct_errs))

    ph_entries = pipeline.autofill_ph_entries(period["ph_map"], config)

    # Đọc ghi chú: từ đầu kỳ tới HÔM NAY (câu trả lời backfill nhắn
    # thứ 7/CN vẫn phải được đọc dù kỳ kết thúc thứ 6)
    notes = notes_store.read_notes_between(
        period["start"], max(send_day, date.today()))
    log.info("Kỳ %s -> %s: %d working day cần dữ liệu, %d ngày lễ, "
             "%d ghi chú.", period["start"], period["end"],
             len(period["expected_days"]), len(period["ph_map"]), len(notes))

    # Ngày nào đã parse + chốt ngay trong ngày thì DÙNG LẠI (nhất quán
    # với cái người dùng đã xác nhận, và đỡ tốn lượt AI). Chỉ gọi AI cho
    # những ngày chưa có kết quả.
    cached_entries, cached_days = daily_store.entries_for_days(
        period["expected_days"])
    missing_days = [d for d in period["expected_days"]
                    if d not in set(cached_days)]
    log.info("Đã có sẵn %d ngày chốt trong ngày; cần AI cho %d ngày.",
             len(cached_days), len(missing_days))

    entries, problems = [], []
    if missing_days:
        session = f"run_{send_day.isoformat()}"
        parsed = pipeline.ai_parse_notes(
            notes, missing_days, config, state, session)
        entries, problems = pipeline.postprocess_ai_days(
            parsed, missing_days, config, state, ph_map=period["ph_map"])

    combined = ph_entries + cached_entries + entries
    issues = validator.find_issues(
        combined, period["expected_days"], period["ph_map"], config)

    questions = problems + ([validator.describe_issues(issues)] if issues else [])
    if questions and not force:
        state["conversation"] = {"awaiting": True,
                                 "send_day": send_day.isoformat()}
        state["draft"] = None
        state_mod.save_state(state)
        audit("PREPARE_NEED_INFO", f"{send_day}: {len(questions)} vấn đề")
        return {"status": "need_info", "questions": questions,
                "send_day": send_day.isoformat()}
    if questions and force:
        log.warning("prepare_draft force=True: bỏ qua %d vấn đề validation",
                    len(questions))
        audit("PREPARE_FORCE", f"{send_day}: bỏ qua {len(questions)} vấn đề")

    draft = pipeline.build_draft(send_day, period, combined)
    state["draft"] = draft
    state["conversation"] = None
    state_mod.save_state(state)
    audit("PREPARE_READY", f"{send_day}: {len(combined)} dòng")

    files = build_preview_files(draft, config)
    return {"status": "ready", "send_day": send_day.isoformat(),
            "preview": pipeline.render_preview(draft, config),
            "files": files, "hold": bool(state.get("hold"))}


def _merged_month_entries(month_key: str, draft: dict, config) -> list:
    """Entries đầy đủ của 1 file tháng = phần NGOÀI KỲ đang có trong
    file + phần TRONG KỲ lấy từ draft (kỳ do draft định nghĩa)."""
    month = date.fromisoformat(month_key + "-01")
    start = date.fromisoformat(draft["period_start"])
    end = date.fromisoformat(draft["period_end"])
    existing = excel_writer.read_month_entries(month, config)
    kept = [e for e in existing if not (start <= e["date"] <= end)]
    return kept + pipeline.draft_entries(draft).get(month_key, [])


def build_preview_files(draft: dict, config) -> list:
    """Dựng file xlsx PREVIEW cho từng tháng của draft (đặt trong
    data\\preview, mang đúng tên bản giao để người dùng thấy tên thật)."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    send_day = date.fromisoformat(draft["send_day"])
    files = []
    for month_key in sorted(draft.get("months", {})):
        month = date.fromisoformat(month_key + "-01")
        name = excel_writer.delivery_file_name(month, send_day, config)
        target = PREVIEW_DIR / name
        excel_writer.write_month_entries(
            month, _merged_month_entries(month_key, draft, config),
            config, path_override=target)
        files.append(target)
    return files


# ---------------------------------------------------------------------
# 2) SỬA BẢN NHÁP THEO LỆNH TỰ NHIÊN
# ---------------------------------------------------------------------

def _build_edit_prompt(draft: dict, user_text: str, config) -> str:
    task_list = "\n".join(f"  - {t}" for t in config.get("task_names"))
    return f"""Bạn là trợ lý sửa BẢN NHÁP timesheet. Dưới đây là bản nháp hiện tại (JSON) và YÊU CẦU SỬA tiếng Việt. Trả về THAO TÁC theo NGÀY, không sửa gì ngoài yêu cầu.

BẢN NHÁP HIỆN TẠI:
{json.dumps(draft["months"], ensure_ascii=False, indent=1)}

YÊU CẦU SỬA: "{user_text}"

TASK NAME hợp lệ:
{task_list}

LUẬT:
- Chỉ đụng các ngày mà yêu cầu nhắc tới. "days" = TOÀN BỘ nội dung MỚI
  của ngày bị sửa (thay nguyên ngày). "delete_days" = ngày xóa trắng.
- Ngày tương đối ("thứ 5", "hôm qua") quy theo các ngày trong bản nháp.
- "hours": chỉ điền khi yêu cầu nói rõ (nửa ngày = 4); không -> null.
- Nghỉ: Annual Leave / Public Holiday / Special Leave / Sick Leave (project = task).
- Mơ hồ -> đưa câu hỏi TIẾNG VIỆT vào "questions", KHÔNG đoán.

TRẢ VỀ JSON:
{{"days": [{{"date": "YYYY-MM-DD",
            "tasks": [{{"project": "...", "task_name": "...",
                        "description": "... hoặc null",
                        "hours": số hoặc null}}]}}],
  "delete_days": ["YYYY-MM-DD", ...],
  "questions": ["...", ...]}}"""


def apply_edit(user_text: str, config, state: dict) -> dict:
    """Sửa draft đang chờ. Trả như prepare_draft: need_info | ready."""
    draft = state.get("draft")
    if not draft:
        raise OrchestratorError("Không có bản nháp nào đang chờ để sửa.")

    send_day = date.fromisoformat(draft["send_day"])
    start = date.fromisoformat(draft["period_start"])
    end = date.fromisoformat(draft["period_end"])
    expected = validator.workdays_between(start, end)
    ph_map = sg_holidays.workday_holidays(start, end, config=config)
    expected = [d for d in expected if d not in ph_map]

    session = f"run_{draft['send_day']}"
    parsed = ai_client.generate_json(
        _build_edit_prompt(draft, user_text, config),
        purpose="friday", config=config, session=session)

    new_entries, problems = pipeline.postprocess_ai_days(
        parsed, expected, config, state, ph_map=ph_map)
    delete_days = set()
    for iso in parsed.get("delete_days", []):
        try:
            delete_days.add(date.fromisoformat(str(iso)))
        except ValueError as e:
            log.debug("AI trả ngày xóa không parse được %r (%s).", iso, e)
            problems.append(f"AI trả ngày xóa không hiểu được: {iso!r}")

    if problems:
        return {"status": "need_info", "questions": problems,
                "send_day": draft["send_day"]}

    touched = delete_days | {e["date"] for e in new_entries}
    old_entries = [e for rows in pipeline.draft_entries(draft).values()
                   for e in rows]
    merged = [e for e in old_entries if e["date"] not in touched] + new_entries

    issues = validator.find_issues(merged, expected, ph_map, config)
    if issues:
        return {"status": "need_info",
                "questions": [validator.describe_issues(issues)],
                "send_day": draft["send_day"]}

    period = {"start": start, "end": end}
    new_draft = pipeline.build_draft(send_day, period, merged)
    state["draft"] = new_draft
    state_mod.save_state(state)
    audit("DRAFT_EDITED", user_text[:120])
    return {"status": "ready", "send_day": draft["send_day"],
            "preview": pipeline.render_preview(new_draft, config),
            "files": build_preview_files(new_draft, config),
            "hold": bool(state.get("hold"))}


# ---------------------------------------------------------------------
# 3) CHỐT GỬI (sau khi người dùng OK)
# ---------------------------------------------------------------------

def _pending_notes_block(state: dict, force: bool):
    """Còn tin chưa xử lý (AI lỗi lúc nhắn) → CHẶN tạo nháp / gửi, trừ khi
    force. Tránh gửi timesheet thiếu mà không ai biết (thêm 24-Sep)."""
    q = state.get("pending_notes") or []
    if not q or force:
        return None
    return {"status": "need_info", "questions": [
        f"Còn {len(q)} tin nhắn CHƯA xử lý (AI lỗi mạng lúc bro nhắn) — "
        "timesheet có thể THIẾU:",
        *[f"“{p['text']}”" for p in q],
        "Nhắn /retrynotes để xử lý lại (hoặc /retrynotes bỏ nếu không cần)."]}


def _leave_summary_safe(config) -> str:
    """Số dư phép TÍNH LẠI từ file Excel vừa ghi/gửi. Lỗi → rỗng (mail
    đã gửi rồi, không được biến thành lỗi)."""
    try:
        import leave_balance
        return leave_balance.short_summary(config, state_mod.load_state())
    except Exception as e:  # noqa: BLE001
        log.warning("Tính số dư phép sau khi gửi lỗi (%s).", e)
        return ""


def _special_leave_notes(months_entries: dict, config, state: dict):
    """Câu email cho các tháng đính kèm có Special Leave. SL chưa gắn
    lễ-thứ-7 nào -> tự gắn lễ T7 chưa dùng gần nhất; hết lễ để gắn ->
    trả câu hỏi (chặn gửi)."""
    notes, questions = [], []
    sl_by_baseline = []
    links = state.get("special_leave_links", {})
    used_sats = set(links.keys())
    for month_key, entries in months_entries.items():
        for e in entries:
            if e["task"] != "Special Leave":
                continue
            sl_iso = e["date"].isoformat()
            sat_iso = next((s for s, sl in links.items() if sl == sl_iso), None)
            if sat_iso is None:
                # Sửa 24-Sep: chỉ gắn lễ-thứ-7 CÒN HẠN 3 tháng tại ngày nghỉ
                # bù, xét cả lễ NĂM TRƯỚC (lễ cuối tháng 12 bù được tới
                # tháng 3), ưu tiên lễ sắp hết hạn. Trước đây: lễ cũ nhất
                # chưa dùng trong CÙNG năm, không kiểm tra hạn.
                import leave_balance
                d = e["date"]
                cands = []
                for y in (d.year - 1, d.year):
                    try:
                        cands += [date.fromisoformat(s) for s, _ in
                                  sg_holidays.saturday_holidays(y, config=config)]
                    except Exception:  # noqa: BLE001
                        pass
                used_ph = {date.fromisoformat(s) for s in used_sats}
                pick = leave_balance.pick_sl_credit(d, cands, used_ph)
                if pick is None:
                    # người dùng đã KHAI số dư nghỉ bù (/updateleave SL n) → chấp
                    # nhận theo số dư đó (vd bù OT, không phải lễ T7), không
                    # bắt khớp lễ; chỉ chặn khi dùng QUÁ số dư (kiểm cuối hàm)
                    if leave_balance._baseline(state, "special", d.year):
                        sl_by_baseline.append(d)
                        log.info("Special Leave %s: theo số dư nhập tay, không gắn lễ T7", sl_iso)
                        # VẪN báo sếp ngày nghỉ bù (không nhắc lễ) — 25-Sep
                        notes.append(mailer.build_special_leave_note(
                            d, None, config, e.get("hours", 8.0)))
                        continue
                    questions.append(
                        f"Ngày {d:%d/%m} ghi Special Leave (nghỉ bù) nhưng không có lễ "
                        "rơi thứ 7 nào CÒN HẠN (3 tháng) để bù. Cách xử lý:\n"
                        "   – có ngày bù thật (vd bù OT): /updateleave SL <số ngày bù> "
                        "rồi /resend\n"
                        f"   – nhầm: /edittimesheet → 'ngày {d:%d/%m}: …nghỉ phép…' "
                        "rồi /resend\n"
                        "   – vẫn gửi như hiện tại: nhắn 'vẫn gởi'")
                    continue
                sat_iso = pick.isoformat()
                used_sats.add(sat_iso)
                state_mod.link_special_leave(state, sat_iso, sl_iso)
                log.info("Tự gắn Special Leave %s <- lễ thứ 7 %s",
                         sl_iso, sat_iso)
            notes.append(mailer.build_special_leave_note(
                e["date"], date.fromisoformat(sat_iso), config, e.get("hours", 8.0)))
    if sl_by_baseline:
        import leave_balance
        r = leave_balance.compute_balance(config, state)
        bal = r["special"]["balance_projected"]
        if bal < -1e-9:
            questions.append(
                f"Special Leave (nghỉ bù) vượt số dư: còn {leave_balance._num(bal)} "
                "ngày sau lần này. Cách xử lý: /updateleave SL <số đúng>, đổi bớt "
                "thành Annual Leave bằng /edittimesheet, hoặc nhắn 'vẫn gởi'.")
    return notes, questions


def prepare_send_preview(config, state: dict, force: bool = False,
                         body_override: str = None) -> dict:
    """Chuẩn bị GỬI nhưng DỪNG trước send_email — trả preview email
    timesheet để người dùng review. Chạy hết validation + build subject/body
    + tính months_entries, NHƯNG KHÔNG ghi Excel, KHÔNG gửi mail.

    Trả {"status": "review", "preview": str, "send_day": iso} hoặc
    {"status": "need_info"/"already_sent"/...} như finalize.
    """
    draft = state.get("draft")
    if not draft:
        return {"status": "no_draft"}
    _pq = _pending_notes_block(state, force)
    if _pq:
        return _pq
    send_day = date.fromisoformat(draft["send_day"])
    if state_mod.already_sent(state, send_day):
        return {"status": "already_sent", "send_day": send_day.isoformat()}

    if not draft.get("months"):
        raise OrchestratorError(
            "Bản nháp không có dữ liệu tháng nào — không gửi mail rỗng.")

    # Validation cấu trúc parsed_days (như finalize)
    _hpd = config.get("hours_per_day") or 8
    _errs = validator.validate_parsed_structure(daily_store.load_all(), _hpd)
    if _errs and not force:
        return {"status": "need_info",
                "questions": ["KHÔNG gửi được — parsed_days lỗi:", *_errs,
                              "Sửa xong gửi lại, hoặc /forcesendmail."]}

    months_entries = {mk: _merged_month_entries(mk, draft, config)
                      for mk in sorted(draft.get("months", {}))}
    sl_notes, sl_questions = _special_leave_notes(
        months_entries, config, state)
    if sl_questions and not force:
        return {"status": "need_info", "questions": sl_questions,
                "send_day": draft["send_day"]}

    # Tính attachments (tên file) mà CHƯA ghi — chỉ để hiển thị
    from pathlib import Path
    att_names = []
    for month_key in months_entries:
        month = date.fromisoformat(month_key + "-01")
        att_names.append(
            Path(excel_writer.delivery_file_name(month, send_day, config)))

    subject = mailer.build_subject(send_day, config)
    body = mailer.build_body(send_day, sl_notes, config)
    if body_override:                 # /manualmail: NGUYÊN VĂN người dùng gõ
        body = body_override
    preview = mailer.build_email_preview(
        send_day, months_entries, subject, body, att_names, config)
    return {"status": "review", "preview": preview,
            "send_day": send_day.isoformat()}


def finalize_and_send(config, state: dict, force: bool = False,
                      body_override: str = None) -> dict:
    """Ghi file tháng thật + bản giao + gửi mail. CHỈ gọi sau khi
    người dùng OK.
    force=True: bỏ qua special_leave questions (người dùng đã xác nhận bypass).
    Trả {"status": "sent", "message": ...} hoặc need_info."""
    draft = state.get("draft")
    if not draft:
        raise OrchestratorError("Không có bản nháp nào đang chờ gửi.")
    _pq = _pending_notes_block(state, force)
    if _pq:
        return _pq
    send_day = date.fromisoformat(draft["send_day"])

    # LỚP PHÒNG THỦ THỨ 2 (độc lập với chặn ở prepare_draft): tuyệt
    # đối không cho phép gửi mail KHÔNG CÓ FILE ĐÍNH KÈM nào, dù draft
    # lọt qua được validator bằng cách nào. Đây là chốt chặn cuối
    # cùng trước khi chạm tới mailer.send_email().
    if not draft.get("months"):
        raise OrchestratorError(
            "Bản nháp này không có dữ liệu tháng nào (0 file đính kèm) "
            "— KHÔNG gửi để tránh mail rỗng cho sếp. Xóa nháp và soạn "
            "lại: nhắn 'gởi timesheet tới hôm nay' đúng ngày cần chốt."
        )

    # CHECKPOINT: validate CẤU TRÚC parsed_days TRƯỚC KHI GỬI MAIL.
    # Lớp chặn cuối — không gửi timesheet hỏng cho sếp (date lệch,
    # tổng ≠ 8h, task trùng). force=True (forcesendmail) vẫn cảnh báo.
    _hpd = config.get("hours_per_day") or 8
    _struct_errs = validator.validate_parsed_structure(
        daily_store.load_all(), _hpd)
    if _struct_errs and not force:
        return {"status": "need_info",
                "questions": [
                    "KHÔNG gửi được — parsed_days có lỗi cấu trúc:",
                    *_struct_errs,
                    "Sửa xong gửi lại, hoặc /forcesendmail để bỏ qua."]}
    elif _struct_errs:
        log.warning("finalize_and_send force=True: bỏ qua %d lỗi cấu "
                    "trúc parsed_days", len(_struct_errs))

    months_entries = {mk: _merged_month_entries(mk, draft, config)
                      for mk in sorted(draft.get("months", {}))}

    sl_notes, sl_questions = _special_leave_notes(
        months_entries, config, state)
    if sl_questions and not force:
        return {"status": "need_info", "questions": sl_questions,
                "send_day": draft["send_day"]}

    attachments = []
    for month_key, entries in months_entries.items():
        month = date.fromisoformat(month_key + "-01")
        excel_writer.write_month_entries(month, entries, config)

        # ── VALIDATION FILE EXCEL trước khi đính kèm ──
        excel_errors = excel_writer.validate_excel_file(month, config)
        if excel_errors and not force:
            log.warning("validate_excel_file: %d lỗi — CHẶN gửi mail",
                        len(excel_errors))
            audit("EXCEL_VALIDATION_FAIL",
                  f"{month_key}: {len(excel_errors)} lỗi")
            return {
                "status": "need_info",
                "questions": excel_errors,
                "send_day": send_day.isoformat(),
                "source": "excel_validation",
            }
        if excel_errors and force:
            log.warning("validate_excel_file: %d lỗi (force=True, bỏ qua)",
                        len(excel_errors))
            audit("EXCEL_VALIDATION_FORCE",
                  f"{month_key}: bỏ qua {len(excel_errors)} lỗi")

        attachments.append(
            excel_writer.make_delivery_copy(month, send_day, config))

    subject = mailer.build_subject(send_day, config)
    body = mailer.build_body(send_day, sl_notes, config)
    if body_override:                 # /manualmail: NGUYÊN VĂN người dùng gõ
        body = body_override
    result = mailer.send_email(
        subject, body, attachments,
        to=config.get("boss_email"), config=config,
        bcc=config.get("bcc_email"))

    # QUAN TRỌNG: mail ĐÃ XÁC NHẬN gửi thành công tại đây. Đánh dấu
    # sent (xóa draft, cập nhật last_sent) NGAY LẬP TỨC — TRƯỚC mọi
    # việc phụ. Nếu để việc phụ (nhớ description...) chạy trước và nó
    # lỡ lỗi (vd ghi state thất bại), exception sẽ bay lên khiến người dùng
    # thấy báo lỗi, tưởng CHƯA gửi, bấm "ok" lại — mà draft vẫn còn
    # nguyên (vì mark_sent chưa chạy) nên lệnh "ok" lần 2 sẽ GỬI MAIL
    # LẦN NỮA cho sếp. Mark trước thì draft bị xóa ngay, "ok" lần 2
    # (nếu có) sẽ báo "chưa có bản nháp" thay vì gửi trùng.
    state_mod.mark_sent(state, send_day)

    # Việc phụ — CHỈ để tối ưu cho lần sau ("giống tuần trước"), không
    # được phép biến thành lỗi che mất việc gửi đã THÀNH CÔNG ở trên.
    try:
        for entries in months_entries.values():
            for e in entries:
                if e["task"] not in config.get("leave_task_names"):
                    state_mod.remember_desc(state, e["project"],
                                            e["description"])
        state_mod.save_state(state)
    except Exception:  # noqa: BLE001 — không được che lấp việc đã gửi OK
        log.exception("Lưu desc_by_project sau khi gửi bị lỗi — bỏ qua, "
                      "mail đã gửi thành công rồi, không ảnh hưởng.")

    audit("TIMESHEET_SENT",
          f"{send_day}; files={[a.name for a in attachments]}; "
          f"sent_check={result['sent_check']}")

    # CLEAN notes.jsonl sau khi gửi THÀNH CÔNG (Phương án A):
    # Kỳ đã đóng → notes cũ không còn cần cho sửa/xóa NLP nữa.
    # parsed_days GIỮ NGUYÊN (tích lũy tháng). Có backup notes tự động.
    # Không được biến thành lỗi che việc gửi đã OK.
    try:
        import notes_store
        clean_result = notes_store.clear_notes_only()
        if clean_result.get("had_notes"):
            log.info("Đã clean notes sau khi gửi (%d dòng, backup %s).",
                     clean_result.get("line_count", 0),
                     clean_result.get("backup"))
            audit("NOTES_CLEANED_AFTER_SEND",
                  f"{clean_result.get('line_count')} dòng, "
                  f"backup={clean_result.get('backup')}")
    except Exception:  # noqa: BLE001 — mail đã gửi OK, clean lỗi không sao
        log.exception("Clean notes sau khi gửi lỗi — bỏ qua, mail đã gửi OK.")

    return {"status": "sent",
            "message": config.get("telegram_success_message"),
            "files": [a.name for a in attachments],
            "sent_check": result["sent_check"],
            "sender": result.get("sender"), "bcc": result.get("bcc"),
            "mode": result.get("mode"),
            "message_id": result.get("message_id"),
            "subject": result.get("subject"), "sent_at": result.get("sent_at"),
            "leave_summary": _leave_summary_safe(config)}


# ---------------------------------------------------------------------
# 4) SỬA DỮ LIỆU QUÁ KHỨ ĐÃ GỬI (file tháng đã ghi, mail đã đi)
# ---------------------------------------------------------------------

def prepare_past_edit(outside_entries: list, delete_days: list,
                      config, state: dict) -> dict:
    """Soạn bản sửa cho các ngày ĐÃ GỬI. KHÔNG ghi file ngay — dựng
    preview + cất pending vào state, chờ người dùng "ok".

    Trả {"status": "need_info"|"ready", ...}
    """
    touched = sorted({e["date"] for e in outside_entries} | set(delete_days))
    if not touched:
        raise OrchestratorError("Không có ngày quá khứ nào để sửa.")

    by_month, problems, warnings = {}, [], []
    for month_key in sorted({d.strftime("%Y-%m") for d in touched}):
        month = date.fromisoformat(month_key + "-01")
        existing = excel_writer.read_month_entries(month, config)
        if not existing:
            problems.append(
                f"Chưa có file timesheet tháng {month_key} để sửa — "
                "kiểm tra lại ngày giúp mình?")
            continue
        month_touched = [d for d in touched
                         if d.strftime("%Y-%m") == month_key]
        kept = [e for e in existing if e["date"] not in set(month_touched)]
        new_rows = [e for e in outside_entries
                    if e["date"].strftime("%Y-%m") == month_key]
        by_month[month_key] = sorted(kept + new_rows,
                                     key=lambda e: e["date"])

        # BẢO VỆ: nếu sau khi sửa/xóa mà CẢ THÁNG rỗng trơn (trường
        # hợp cực hiếm — chỉ xảy ra khi mọi dòng duy nhất của tháng
        # đó đều bị xóa), cảnh báo THẬT TO thay vì âm thầm cho phép,
        # vì đây là XÓA TRẮNG TOÀN BỘ 1 THÁNG đã gửi sếp.
        if existing and not by_month[month_key]:
            warnings.append(
                f"CẢ THÁNG {month_key} sẽ TRỐNG TRƠN sau khi sửa (mọi "
                "dòng đều bị xóa) — sếp đã nhận bản có dữ liệu tháng "
                "này rồi. Kiểm tra thật kỹ trước khi OK!")

        # Mỗi ngày bị đụng vẫn phải đúng 8h (trừ ngày bị xóa hẳn)
        for d in month_touched:
            rows = [e for e in new_rows if e["date"] == d]
            if not rows:
                warnings.append(
                    f"Ngày {d.strftime('%d/%m')} sẽ bị XÓA TRẮNG khỏi "
                    "timesheet đã gửi — sếp từng thấy dòng của ngày này.")
                continue
            total = round(sum(float(r["hours"]) for r in rows), 2)
            if abs(total - config.get("hours_per_day")) > 1e-9:
                problems.append(
                    f"Ngày {d.strftime('%d/%m')} sau khi sửa chỉ còn "
                    f"{total:g}h (phải đúng {config.get('hours_per_day')}h)")

    if problems:
        return {"status": "need_info", "questions": problems}

    state["past_edit"] = {
        "months": {mk: [{**e, "date": e["date"].isoformat()} for e in rows]
                   for mk, rows in by_month.items()},
        "touched": [d.isoformat() for d in touched],
        "created_at": date.today().isoformat(),
    }
    state_mod.save_state(state)
    audit("PAST_EDIT_PREPARED",
          f"{[d.isoformat() for d in touched]}")

    lines = ["SỬA TIMESHEET ĐÃ GỬI", ""]
    for d in touched:
        rows = [e for e in outside_entries if e["date"] == d]
        thu = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][d.weekday()]
        if not rows:
            lines.append(f"{thu} {d.strftime('%d/%m')}: XÓA TRẮNG")
            continue
        lines.append(f"{thu} {d.strftime('%d/%m')}:")
        for e in rows:
            desc = f" | {e['description']}" if e.get("description") else ""
            lines.append(f"   {e['hours']:g}h {e['task']} — "
                         f"{e['project']}{desc}")
    if warnings:
        lines += [""] + [f"LƯU Ý: {w}" for w in warnings]
    lines += ["", f"File sẽ sửa: {', '.join(sorted(by_month))}"]
    return {"status": "ready", "preview": "\n".join(lines),
            "months": sorted(by_month)}


def apply_past_edit(config, state: dict) -> dict:
    """người dùng đã "ok": ghi thật vào file tháng (có backup như mọi khi).
    KHÔNG gửi mail, KHÔNG đụng last_sent — bản sửa đi theo chuyến gửi
    kế tiếp, hoặc người dùng nhắn "gởi lại" để gửi ngay."""
    pending = state.get("past_edit")
    if not pending:
        raise OrchestratorError("Không có bản sửa quá khứ nào đang chờ.")

    written = []
    touched_days_set = set()
    for month_key, rows in sorted(pending["months"].items()):
        month = date.fromisoformat(month_key + "-01")
        entries = [{**e, "date": date.fromisoformat(e["date"])}
                   for e in rows]
        info = excel_writer.write_month_entries(month, entries, config)
        written.append(info["path"].name)
        for e in entries:
            touched_days_set.add(e["date"])

    # ĐỒNG BỘ parsed_days.json với Excel vừa ghi — TRÁNH LỆCH NGUỒN.
    # Nếu không, /summary và prepare_draft đọc parsed_days cũ sẽ hiểu
    # sai / đè lại Excel bằng dữ liệu cũ. Ghi lại từng ngày đã sửa.
    # rows trong pending["months"] là TOÀN BỘ dòng của tháng đó (đã
    # merge), nên gom lại theo ngày rồi save_day cho các ngày touched.
    all_rows_by_day: dict = {}
    for month_key, rows in pending["months"].items():
        for e in rows:
            d = date.fromisoformat(e["date"])
            all_rows_by_day.setdefault(d, []).append(
                {**e, "date": d})
    # Chỉ cập nhật parsed_days cho các ngày THỰC SỰ bị sửa (touched)
    touched_dates = set()
    for t in pending.get("touched", []):
        try:
            touched_dates.add(date.fromisoformat(str(t)))
        except (ValueError, TypeError):
            pass
    for d in touched_dates:
        rows_for_d = all_rows_by_day.get(d, [])
        if rows_for_d:
            daily_store.save_day(d, rows_for_d)
        else:
            # ngày bị xóa hoàn toàn → xóa khỏi parsed_days
            daily_store.forget_day(d)
    log.info("apply_past_edit: đồng bộ parsed_days cho %d ngày sửa.",
             len(touched_dates))

    state["past_edit"] = None
    state_mod.save_state(state)
    audit("PAST_EDIT_APPLIED", f"{pending['touched']} -> {written}")
    return {"status": "past_edit_done", "files": written,
            "months": sorted(pending["months"])}


def apply_edit_smart(outside_entries: list, delete_days: list,
                     config, state: dict) -> dict:
    """Sửa timesheet THÔNG MINH — tự phân biệt ngày đã gửi vs chưa gửi:

    - Ngày ĐÃ GỬI (< last_sent, hoặc tháng có file Excel đã tạo):
      → dùng luồng past_edit (ghi Excel + parsed_days).
    - Ngày CHƯA GỬI (trong kỳ hiện tại, chưa có trong Excel):
      → chỉ ghi parsed_days (daily_store). Sẽ vào Excel khi /weeklyrun.

    Cả 2 loại đều đồng bộ parsed_days.
    Trả {"status": "edit_done", "sent_days": [...], "unsent_days": [...],
         "files": [...], "months": [...]}.
    """
    last_sent = state_mod.last_sent_date(state)
    all_days = sorted({e["date"] for e in outside_entries} | set(delete_days))

    # Phân loại: ngày đã gửi vs chưa gửi
    sent_days, unsent_days = [], []
    for d in all_days:
        # "đã gửi" = ngày <= last_sent (đã nằm trong file Excel đã gửi)
        if last_sent is not None and d <= last_sent:
            sent_days.append(d)
        else:
            unsent_days.append(d)

    result = {"status": "edit_done", "sent_days": [], "unsent_days": [],
              "files": [], "months": []}

    # --- Ngày CHƯA GỬI: chỉ ghi parsed_days ---
    if unsent_days:
        by_day: dict = {}
        for e in outside_entries:
            if e["date"] in unsent_days:
                by_day.setdefault(e["date"], []).append(e)
        for d in unsent_days:
            rows = by_day.get(d, [])
            if rows:
                daily_store.save_day(d, rows)
            elif d in delete_days:
                daily_store.forget_day(d)
        result["unsent_days"] = [d.isoformat() for d in unsent_days]
        log.info("apply_edit_smart: ghi parsed_days cho %d ngày chưa gửi.",
                 len(unsent_days))

    # --- Ngày ĐÃ GỬI: luồng past_edit (Excel + parsed_days) ---
    if sent_days:
        sent_entries = [e for e in outside_entries if e["date"] in sent_days]
        sent_deletes = [d for d in delete_days if d in sent_days]
        prep = prepare_past_edit(sent_entries, sent_deletes, config, state)
        if prep.get("status") == "need_info":
            return {"status": "need_info", "questions": prep["questions"]}
        applied = apply_past_edit(config, state_mod.load_state())
        result["sent_days"] = [d.isoformat() for d in sent_days]
        result["files"] = applied.get("files", [])
        result["months"] = applied.get("months", [])

    return result


def prepare_resend_preview(month_keys: list, config, state: dict,
                           force: bool = False, body_override: str = None) -> dict:
    """Preview cho 'gởi lại' — y hệt preview thứ 6 (From/To/Bcc/Subject/
    nội dung email/D-E-F từng ngày), đọc số liệu từ file Excel tháng
    (bản đã sửa). KHÔNG tạo file giao, KHÔNG gửi.
    Trả {"status": "review", "preview": str} hoặc need_info."""
    from pathlib import Path
    send_day = state_mod.last_sent_date(state) or date.today()
    months_entries, att_names = {}, []
    for month_key in month_keys:
        month = date.fromisoformat(month_key + "-01")
        months_entries[month_key] = excel_writer.read_month_entries(
            month, config)
        att_names.append(
            Path(excel_writer.delivery_file_name(month, send_day, config)))
    notes, questions = _special_leave_notes(months_entries, config, state)
    if questions and not force:            # force = người dùng nhắn 'vẫn gởi'
        return {"status": "need_info", "questions": questions}
    subject = mailer.build_subject(send_day, config)
    body = mailer.build_body(send_day, notes, config)
    if body_override:                 # /manualmail: NGUYÊN VĂN người dùng gõ
        body = body_override
    preview = mailer.build_email_preview(
        send_day, months_entries, subject, body, att_names, config)
    preview = preview.replace(
        "📧 EMAIL TIMESHEET SẼ GỬI SẾP — XEM TRƯỚC:",
        "📧 GỞI LẠI TIMESHEET ĐÃ SỬA — XEM TRƯỚC:", 1)
    return {"status": "review", "preview": preview}


def resend_months(month_keys: list, config, state: dict,
                  force: bool = False, body_override: str = None) -> dict:
    """Gửi lại file tháng cho sếp NGAY (sau khi sửa quá khứ).
    Dùng mốc last_sent làm ngày trong tiêu đề/tên file: bản chất đây
    là gửi lại đúng kỳ đã báo, chỉ khác là số liệu đã sửa."""
    send_day = state_mod.last_sent_date(state) or date.today()
    attachments, sl_notes = [], []
    months_entries = {}
    for month_key in month_keys:
        month = date.fromisoformat(month_key + "-01")
        months_entries[month_key] = excel_writer.read_month_entries(
            month, config)
        attachments.append(
            excel_writer.make_delivery_copy(month, send_day, config))

    notes, questions = _special_leave_notes(months_entries, config, state)
    if questions and not force:            # force = người dùng nhắn 'vẫn gởi'
        return {"status": "need_info", "questions": questions}
    sl_notes = notes

    subject = mailer.build_subject(send_day, config)
    body = mailer.build_body(send_day, sl_notes, config)
    if body_override:                 # /manualmail: NGUYÊN VĂN người dùng gõ
        body = body_override
    result = mailer.send_email(subject, body, attachments,
                               to=config.get("boss_email"), config=config,
                               bcc=config.get("bcc_email"))
    audit("TIMESHEET_RESENT",
          f"{send_day}; files={[a.name for a in attachments]}")
    return {"status": "sent",
            "message": config.get("telegram_success_message"),
            "files": [a.name for a in attachments],
            "sent_check": result["sent_check"],
            "sender": result.get("sender"), "bcc": result.get("bcc"),
            "mode": result.get("mode"),
            "message_id": result.get("message_id"),
            "subject": result.get("subject"), "sent_at": result.get("sent_at"),
            "leave_summary": _leave_summary_safe(config)}


# ---------------------------------------------------------------------
# Gửi Telegram kiểu đồng bộ (cho weekly_run)
# ---------------------------------------------------------------------

def chunk_text(text: str, size: int = TELEGRAM_CHUNK) -> list:
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > size:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


def notify(text: str, config, files=None) -> None:
    """Nhắn người dùng qua Telegram (kèm file nếu có), chạy đồng bộ."""
    from telegram import Bot

    async def _send():
        async with Bot(config.telegram_bot_token) as bot:
            chat_id = config.telegram_allowed_chat_id
            for part in chunk_text(text):
                await bot.send_message(chat_id=chat_id, text=part)
            for path in files or []:
                with open(path, "rb") as f:
                    await bot.send_document(chat_id=chat_id, document=f,
                                            filename=path.name)

    asyncio.run(_send())
